"""project2 真实 HTTP 端到端验证：注册 → 登录 → 上传文档 → 多 Agent SSE 流 → 查步骤 → 清理。"""
from __future__ import annotations

import json
import uuid

import httpx

BASE = "http://127.0.0.1:8765/api/v1"
USERNAME = "e2e_" + uuid.uuid4().hex[:8]
PASSWORD = "e2e_pass_123"

DOC_TEXT = """OfferPilot 系统设计说明

第一部分 整体架构
OfferPilot 是一个求职辅助系统，核心功能是把候选人简历与职位描述做匹配打分。
后端采用 FastAPI 五层架构，依次是 api、service、repository、model，依赖方向单向向下。
业务数据使用 PostgreSQL 存储，简历与职位描述的向量表示使用 pgvector 扩展存储。
向量列维度为 768，与本地 nomic-embed-text 模型输出的维度保持一致。

第二部分 检索流程
检索阶段先用余弦距离做向量相似度召回，取回 top_k 个候选片段。
召回之后按分数阈值过滤，把相似度低于阈值的片段丢弃，避免把无关内容送进生成阶段。
命中过的检索结果会写入 Redis 缓存，同一个问题再次提问时直接读缓存，省掉一次向量化与一次数据库查询。

第三部分 多 Agent 协作
多 Agent 协作由 LangGraph 状态图驱动，包含 Planner、Retriever、Generator、Reviewer 四个节点。
Planner 节点负责把用户问题拆解成一到三个可以独立检索的子问题。
Retriever 节点对每一个子问题分别检索，把命中的片段累积进共享状态。
Generator 节点基于累积的上下文生成回答草稿。
Reviewer 节点负责质检，不通过时把控制权交回 Generator 重写，超过最大重试次数才终止。

第四部分 可观测性
每一次运行都会在 agent_runs 表落一条记录，状态从 pending 依次推进到 completed 或 failed。
每个节点的执行都会在 agent_steps 表落一条记录，包含节点名、尝试次数、状态与耗时毫秒数。
前端通过 SSE 订阅节点级的 node_start 与 node_done 事件，实时展示每个 Agent 的执行进度。
状态图使用 checkpoint 保存中间状态，节点因外部依赖故障中断后可以从中断处恢复继续执行。
"""

results: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  → {detail}" if detail else ""))
    results.append((label, ok, detail))


with httpx.Client(timeout=120.0) as c:
    print("\n【1】注册 + 登录")
    r = c.post(f"{BASE}/auth/register", json={"username": USERNAME, "password": PASSWORD})
    check("注册返回 200", r.status_code == 200, f"HTTP {r.status_code}")
    r = c.post(f"{BASE}/auth/login", json={"username": USERNAME, "password": PASSWORD})
    check("登录返回 200", r.status_code == 200, f"HTTP {r.status_code}")
    body = r.json()
    token = body["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    r = c.get(f"{BASE}/auth/me", headers=headers)
    check("带 token 取到用户信息", r.status_code == 200 and r.json()["data"]["username"] == USERNAME)

    print("\n【2】上传知识库文档")
    r = c.post(
        f"{BASE}/documents/upload",
        headers=headers,
        files={"file": ("offerpilot.txt", DOC_TEXT.encode("utf-8"), "text/plain")},
    )
    check("上传返回 200", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
    doc = r.json()["data"]
    doc_id = doc["id"]
    check("文档切分为多个 chunk", doc.get("chunk_count", 0) >= 2, f"chunk_count={doc.get('chunk_count')}")

    r = c.get(f"{BASE}/documents", headers=headers)
    listing = r.json()["data"]
    check("文档列表能查到该文档", any(d["id"] == doc_id for d in listing["items"]), f"total={listing['total']}")

    print("\n【3】多 Agent SSE 流式问答")
    session_id = "e2e-" + uuid.uuid4().hex[:8]
    events: list[dict] = []
    with c.stream(
        "POST",
        f"{BASE}/agent/runs/stream",
        headers=headers,
        json={"session_id": session_id, "question": "OfferPilot 的多 Agent 有哪几个节点？Reviewer 做什么？"},
    ) as resp:
        check("SSE 返回 200", resp.status_code == 200, f"HTTP {resp.status_code}")
        for line in resp.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

    kinds = [e.get("type") for e in events]
    print(f"     收到事件 {len(events)} 个: {sorted(set(kinds))}")
    check("出现 node_start 事件", "node_start" in kinds)
    check("出现 node_done 事件", "node_done" in kinds)
    done_nodes = [e["node"] for e in events if e.get("type") == "node_done"]
    check(
        "四个节点都跑过",
        {"planner", "retriever", "generator", "reviewer"}.issubset(set(done_nodes)),
        f"实际 {done_nodes}",
    )
    complete = [e for e in events if e.get("type") == "done"]
    answers = [e for e in events if e.get("type") == "final_answer"]
    check("出现 done 事件", bool(complete))
    check("出现 final_answer 事件", bool(answers))
    retriever_summaries = [
        e.get("output_summary", "") for e in events if e.get("type") == "node_done" and e.get("node") == "retriever"
    ]
    got_docs = any("got 0 docs" not in s for s in retriever_summaries)
    check("Retriever 真的检索到文档片段", got_docs, f"{retriever_summaries}")
    run_id = answers[0]["run_id"] if answers else ""
    answer = answers[0].get("answer", "") if answers else ""
    print(f"     final_answer: {answer[:80]}...")
    check("回答非空", bool(answer.strip()))
    check(
        "回答提到 Reviewer 的职责",
        "质检" in answer or "review" in answer.lower(),
        answer[:60],
    )

    print("\n【4】运行记录与步骤落库")
    r = c.get(f"{BASE}/agent/runs/{run_id}", headers=headers)
    check("按 run_id 查到运行详情", r.status_code == 200, f"HTTP {r.status_code}")
    payload = r.json()["data"]
    run = payload["run"]
    check("运行状态 completed", run["status"] == "completed", run["status"])
    steps = payload["steps"]
    check("步骤数 >= 5", len(steps) >= 5, f"{len(steps)} 步")
    check("所有步骤 success", all(s["status"] == "success" for s in steps))
    check(
        "每步都记了耗时 duration_ms",
        all(s["duration_ms"] is not None for s in steps),
        f"{[s['duration_ms'] for s in steps]}",
    )
    for s in steps:
        print(f"       {s['node_name']:10s} #{s['attempt']} {s['status']:8s} {s['duration_ms']}ms  {s['output_summary'] or ''}")

    r = c.get(f"{BASE}/agent/runs", headers=headers, params={"session_id": session_id})
    runs = r.json()["data"]
    run_items = runs["items"] if isinstance(runs, dict) else runs
    check("运行列表能查到该 run", any(x["run_id"] == run_id for x in run_items))

    print("\n【5】清理")
    r = c.delete(f"{BASE}/documents/{doc_id}", headers=headers)
    check("删除文档返回 200", r.status_code == 200, f"HTTP {r.status_code}")

failed = [label for label, ok, _ in results if not ok]
print("\n" + ("全部通过" if not failed else f"存在失败: {failed}"))
raise SystemExit(1 if failed else 0)
