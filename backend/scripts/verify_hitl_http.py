"""人工介入的 HTTP 层验证：暂停 → 查待裁决 → 带裁决值恢复。

用 FastAPI TestClient 走真实路由与应用入口，不另起端口；只把审核节点的模型
换成固定返回「不通过」的假模型，其余全部走真实实现（鉴权、路由、服务层、图）。

覆盖：
  1. 开 HITL 后 POST /agent/runs 返回 status=awaiting_review 且 interrupt 非空；
  2. GET /agent/runs/{run_id} 里 run.status 是 awaiting_review，步骤无 failed；
  3. POST /agent/runs/resume 不带 decision 时保持暂停；
  4. POST /agent/runs/resume 带 decision=accept 后转 completed，答案采纳草稿。

用法：
    uv run python -m scripts.verify_hitl_http
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.config.settings import settings
from app.services import agent_dynamic, agent_service

REVIEWER_MARKER = "回答质量审核专家"
REJECT_JSON = '{"passed": false, "feedback": "回答缺少引用，请补充出处"}'
USERNAME = "hitl_" + uuid.uuid4().hex[:8]
PASSWORD = "hitl_pass_123"
QUESTION = "介绍一下系统的检索流程"

RESULTS: list[tuple[str, bool]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    """记一条结论并打印。"""
    RESULTS.append((label, ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  → {detail}" if detail else ""))


def _make_stub(real_llm: Any) -> RunnableLambda:
    """把审核节点的模型换成固定返回「不通过」，其余节点转真实模型。

    real_llm 必须在打补丁之前取好：补丁生效后再调 agent_service.get_llm()
    会拿回假模型本身，形成无限递归。
    """

    def route(prompt_value: Any) -> Any:
        if REVIEWER_MARKER in str(prompt_value):
            return AIMessage(content=REJECT_JSON)
        return real_llm.invoke(prompt_value)

    return RunnableLambda(route)


def main() -> int:
    """跑完 HTTP 层的人工介入验证。"""
    settings.AGENT_HITL_ENABLED = True
    # 默认就是确定性编排，这里显式写清楚，避免受外部环境变量影响
    settings.AGENT_ORCHESTRATION_MODE = "deterministic"

    from app.main import app

    real_llm = agent_service.get_llm()
    stub = _make_stub(real_llm)
    llm_factory = lambda: stub  # noqa: E731 — patch.object 要的是零参工厂

    client = TestClient(app)
    base = settings.API_PREFIX

    print("=" * 72)
    print("人工介入 HTTP 层验证")
    print(
        f"orchestration={settings.AGENT_ORCHESTRATION_MODE} "
        f"hitl={settings.AGENT_HITL_ENABLED}"
    )
    print("=" * 72)

    print("\n[1] 注册并登录")
    response = client.post(
        f"{base}/auth/register", json={"username": USERNAME, "password": PASSWORD}
    )
    check("注册返回 200", response.status_code == 200, f"HTTP {response.status_code}")
    response = client.post(
        f"{base}/auth/login", json={"username": USERNAME, "password": PASSWORD}
    )
    check("登录返回 200", response.status_code == 200, f"HTTP {response.status_code}")
    token = response.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    try:
        with patch.object(agent_service, "get_llm", llm_factory):
            with patch.object(agent_dynamic, "get_llm", llm_factory):
                print("\n[2] 发起运行，应停在人工介入点")
                response = client.post(
                    f"{base}/agent/runs",
                    json={"session_id": "hitl-http", "question": QUESTION},
                    headers=headers,
                )
                body = response.json()
                run_id = (body.get("data") or {}).get("run_id", "")
                print(f"  run_id={run_id} body={str(body)[:220]}")
                check("返回 200", response.status_code == 200)
                check(
                    "status=awaiting_review",
                    body["data"]["status"] == "awaiting_review",
                    f"status={body['data']['status']}",
                )
                check(
                    "interrupt 带出待裁决内容",
                    bool(body["data"].get("interrupt")),
                    f"interrupt 键={sorted((body['data'].get('interrupt') or {}).keys())}",
                )
                draft = (body["data"].get("interrupt") or {}).get("draft", "")

                print("\n[3] 查询运行详情")
                response = client.get(f"{base}/agent/runs/{run_id}", headers=headers)
                detail = response.json()["data"]
                steps = detail["steps"]
                failed = [s for s in steps if s["status"] == "failed"]
                for step in steps:
                    print(
                        f"     {step['node_name']:<10} #{step['attempt']} "
                        f"{step['status']:<8} {(step['output_summary'] or '')[:70]}"
                    )
                check(
                    "运行状态落库为 awaiting_review",
                    detail["run"]["status"] == "awaiting_review",
                    f"status={detail['run']['status']}",
                )
                check("暂停不被当成节点失败", not failed, f"failed 数={len(failed)}")

                print("\n[4] 不带裁决值恢复")
                response = client.post(
                    f"{base}/agent/runs/resume",
                    json={"run_id": run_id},
                    headers=headers,
                )
                again = response.json()["data"]
                check(
                    "保持暂停且回传 interrupt",
                    again["status"] == "awaiting_review" and bool(again.get("interrupt")),
                    f"status={again['status']}",
                )

                print("\n[5] 带裁决值 accept 恢复")
                response = client.post(
                    f"{base}/agent/runs/resume",
                    json={"run_id": run_id, "decision": "accept"},
                    headers=headers,
                )
                resumed = response.json()["data"]
                check(
                    "状态转 completed",
                    resumed["status"] == "completed",
                    f"status={resumed['status']}",
                )
                response = client.get(f"{base}/agent/runs/{run_id}", headers=headers)
                final = response.json()["data"]["run"]
                check(
                    "最终答案采纳了暂停时的草稿",
                    bool(final["final_answer"])
                    and bool(draft)
                    and final["final_answer"] == draft,
                    f"answer 前 60 字={str(final['final_answer'])[:60]!r}",
                )
    finally:
        settings.AGENT_HITL_ENABLED = False

    print("\n" + "=" * 72)
    passed = sum(1 for _, ok in RESULTS if ok)
    for label, ok in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {label}")
    print(f"结果: {passed}/{len(RESULTS)} 项通过")
    print("=" * 72)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
