"""动态编排与人工介入的端到端验证脚本。

前置条件：
  1. PostgreSQL 已启动（make infra-up），目标用户已有文档片段
  2. .env 配好 LLM_API_KEY；Embedding 走本地 Ollama 的 nomic-embed-text

脚本直接调用服务层，不经过 HTTP，覆盖五组能力：
  1. 动态路由：每一步去向由 supervisor 决定，step 日志里能看到它的决策与理由；
  2. 五层护栏：非法目标、原地打转、工具调用上限、步数上限都退回规则路径，图仍收敛；
  3. 工具生态：supervisor 派发到 tool 后工具真实执行，结果记进工具轨迹；
  4. 求值安全：算术表达式走 AST 白名单求值，注入型表达式一律拒绝；
  5. 人工介入：质检不通过暂停为 awaiting_review，带裁决值 resume 能跑完。

用法：
    uv run python -m scripts.verify_dynamic_agent [user_id]
"""
from __future__ import annotations

import sys
from typing import Any
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.config.database import SessionLocal
from app.config.settings import settings
from app.services import agent_dynamic, agent_service
from app.services.agent_dynamic import tool_calculate
from app.services.agent_service import MultiAgentService

DEFAULT_USER_ID = 1
SESSION_ID = "verify-dynamic"

# 假模型靠提示词里的标志句判断自己正在被哪个节点调用
SUPERVISOR_MARKER = "多 Agent 协作流程的调度员"
TOOL_MARKER = "工具调用规划器"
REVIEWER_MARKER = "回答质量审核专家"

REJECT_JSON = '{"passed": false, "feedback": "回答缺少文档依据，请补充引用"}'
ILLEGAL_TARGET_JSON = '{"next": "delete_all_data", "reason": "越权目标"}'
TOOL_TARGET_JSON = '{"next": "tool", "reason": "先算个数"}'
CALC_JSON = '{"tool": "calculate", "arguments": {"expression": "120*0.85"}}'
NO_TOOL_JSON = '{"tool": null, "arguments": {}, "reason": "无需工具"}'

QUESTION = "这份问卷的主题是什么，包含哪些题目类型？"
WORKERS = {"planner", "retriever", "generator", "reviewer"}

RESULTS: list[tuple[str, bool]] = []


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------


def _record(name: str, passed: bool, detail: str = "") -> None:
    """记一条验证结论并打印。"""
    RESULTS.append((name, passed))
    print(f"{'✅' if passed else '❌'} {name}")
    if detail:
        print(f"   {detail}")


def _print_steps(steps: list[Any]) -> None:
    """打印 step 日志的节点、状态与摘要。"""
    for step in steps:
        summary = (step.output_summary or "")[:96]
        print(f"   {step.node_name:<11} #{step.attempt}  {step.status:<8} {summary}")


def _stub_llm(routes: dict[str, str]) -> RunnableLambda:
    """构造假模型：提示词命中某个标志句时返回固定 JSON，否则转给真实模型。

    只替换被验证的决策点，工人节点仍然走真实模型，这样测的是编排与护栏，
    不是模型能力。注意 get_llm 在业务代码里是「调用形式」而非对象，
    因此打补丁时要换成零参工厂，不能直接把 Runnable 塞进去。
    """
    real = agent_service.get_llm()

    def route(prompt_value: Any) -> Any:
        text = str(prompt_value)
        for marker, payload in routes.items():
            if marker in text:
                return AIMessage(content=payload)
        return real.invoke(prompt_value)

    return RunnableLambda(route)


def _llm_factory(routes: dict[str, str]) -> Any:
    """返回一个可给 patch.object 用的零参工厂。"""
    stub = _stub_llm(routes)
    return lambda: stub


def _run(service: MultiAgentService, user_id: int) -> dict[str, Any]:
    """跑一次问答并把失败原因打出来，方便定位。"""
    result = service.run(user_id=user_id, session_id=SESSION_ID, question=QUESTION)
    if result["status"] == "failed":
        print(f"   ⚠️ run failed: {result.get('error_message')}")
    return result


def _supervisor_summaries(steps: list[Any]) -> list[str]:
    """取出 supervisor 节点写下的决策摘要。"""
    return [
        step.output_summary or "" for step in steps if step.node_name == "supervisor"
    ]


def _steps_of(service: MultiAgentService, run_id: str) -> list[Any]:
    """取某次运行的 step 列表。"""
    detail = service.get_run_detail(run_id)
    return detail["steps"] if detail else []


# ---------------------------------------------------------------------------
# 第 1 组：求值安全（不依赖 LLM 与数据库）
# ---------------------------------------------------------------------------


def check_ast_eval_safety() -> None:
    """算术表达式只放行白名单运算，注入型表达式必须被拒。"""
    print("\n[1] 工具求值安全：AST 白名单")

    safe_cases: list[tuple[str, str]] = [
        ("120*0.85", "120*0.85 = 102"),
        ("(3+5)/2", "(3+5)/2 = 4"),
        ("2**10", "2**10 = 1024"),
        ("-7%3", "-7%3 = 2"),
    ]
    for expression, expect in safe_cases:
        got = tool_calculate({"expression": expression}, {})
        _record(f"允许: {expression}", got == expect, f"got={got!r}")

    unsafe = [
        "__import__('os').system('id')",
        "().__class__.__bases__",
        "[x for x in (1,2)]",
        "lambda: 1",
        "print(1)",
        "1 if True else 2",
    ]
    for expression in unsafe:
        got = tool_calculate({"expression": expression}, {})
        _record(
            f"拒绝: {expression[:32]}",
            got.startswith("计算失败"),
            f"got={got!r}",
        )

    missing = tool_calculate({}, {})
    _record("缺参数时报错而非崩溃", missing.startswith("calculate 缺少"), missing)


# ---------------------------------------------------------------------------
# 第 2 组：动态路由
# ---------------------------------------------------------------------------


def check_dynamic_routing(service: MultiAgentService, user_id: int) -> None:
    """dynamic 模式下 supervisor 应出现在每一步之前，并把四个工人都派发一遍。"""
    print("\n[2] 动态路由：路径由 supervisor 决定")
    result = _run(service, user_id)
    steps = _steps_of(service, result["run_id"])
    sequence = [step.node_name for step in steps]

    print(f"   run_id={result['run_id']} status={result['status']}")
    print(f"   节点序列: {' -> '.join(sequence)}")
    _print_steps(steps)

    decisions = [s for s in _supervisor_summaries(steps) if "next=" in s]
    print(f"   supervisor 决策 {len(decisions)} 次，前两条: {decisions[:2]}")

    reached = WORKERS & set(sequence)
    fallbacks = [
        s
        for s in _supervisor_summaries(steps)
        if "回退" in s and "next=" in s
    ]
    _record(
        "每步都由 supervisor 决策",
        result["status"] == "completed" and len(decisions) >= 4,
        f"决策次数={len(decisions)}，状态={result['status']}",
    )
    _record(
        "四个工人节点都被派发过",
        reached == WORKERS,
        f"实际到达={sorted(reached)}",
    )
    _record(
        "路线以模型决策为主，护栏只做兜底",
        len(fallbacks) < len(decisions),
        f"模型决策 {len(decisions)} 次，其中护栏兜底 {len(fallbacks)} 次",
    )


# ---------------------------------------------------------------------------
# 第 3 组：护栏
# ---------------------------------------------------------------------------


def check_guardrail_illegal_target(service: MultiAgentService, user_id: int) -> None:
    """模型给出白名单外目标时，应回退规则路由并继续跑完。"""
    print("\n[3] 护栏 A：模型给出非法目标")
    stub = _llm_factory(
        {SUPERVISOR_MARKER: ILLEGAL_TARGET_JSON, TOOL_MARKER: NO_TOOL_JSON}
    )
    with patch.object(agent_dynamic, "get_llm", stub):
        result = _run(service, user_id)

    steps = _steps_of(service, result["run_id"])
    _print_steps(steps)
    fallbacks = [s for s in _supervisor_summaries(steps) if "非法目标" in s]
    _record(
        "非法目标回退规则路由且流程收敛",
        result["status"] == "completed" and bool(fallbacks),
        f"命中 {len(fallbacks)} 次回退，状态={result['status']}",
    )


def check_guardrail_no_progress(service: MultiAgentService, user_id: int) -> None:
    """模型反复派回同一节点且状态无变化时，应判定打转并回退规则路由。"""
    print("\n[4] 护栏 B：原地打转检测")
    # 无论进展如何都派回 planner，模拟弱模型死循环
    stub = _llm_factory(
        {
            SUPERVISOR_MARKER: '{"next": "planner", "reason": "再拆一次"}',
            TOOL_MARKER: NO_TOOL_JSON,
        }
    )
    with patch.object(agent_dynamic, "get_llm", stub):
        result = _run(service, user_id)

    steps = _steps_of(service, result["run_id"])
    _print_steps(steps)
    stuck = [s for s in _supervisor_summaries(steps) if "重复选择且无进展" in s]
    sequence = [s.node_name for s in steps]
    _record(
        "打转被识别并回退规则路由",
        result["status"] == "completed" and bool(stuck),
        f"命中 {len(stuck)} 次，状态={result['status']}",
    )
    _record(
        "打转后流程继续推进到其他工人",
        len(set(sequence) & WORKERS) >= 3,
        f"实际到达={sorted(set(sequence) & WORKERS)}",
    )


def check_tool_ecosystem(service: MultiAgentService, user_id: int) -> None:
    """supervisor 派发到 tool 时工具真实执行，次数封顶后回退规则路由。"""
    print("\n[5] 工具生态：派发 → 执行 → 次数封顶")
    stub = _llm_factory(
        {
            SUPERVISOR_MARKER: TOOL_TARGET_JSON,
            TOOL_MARKER: CALC_JSON,
        }
    )
    with patch.object(agent_dynamic, "get_llm", stub):
        result = _run(service, user_id)

    steps = _steps_of(service, result["run_id"])
    _print_steps(steps)
    sequence = [s.node_name for s in steps]
    tool_steps = [s for s in steps if s.node_name == "tool"]
    executed = [s for s in tool_steps if "= 102" in (s.output_summary or "")]
    capped = [s for s in _supervisor_summaries(steps) if "工具调用已达上限" in s]

    _record(
        "supervisor 能派发到 tool 节点",
        "tool" in sequence,
        f"tool 节点执行 {len(tool_steps)} 次",
    )
    _record(
        "工具真实执行并落库结果",
        bool(executed),
        f"命中 {len(executed)} 次 calculate 结果，例如 "
        f"{(executed[0].output_summary if executed else '')!r}",
    )
    _record(
        f"工具调用封顶 {settings.AGENT_MAX_TOOL_CALLS} 次后回退规则路由",
        len(tool_steps) <= settings.AGENT_MAX_TOOL_CALLS
        and bool(capped)
        and result["status"] == "completed",
        f"tool 执行 {len(tool_steps)} 次，回退 {len(capped)} 次，"
        f"状态={result['status']}",
    )


def check_guardrail_max_steps(service: MultiAgentService, user_id: int) -> None:
    """步数上限触发时应直接收尾，不进入死循环。"""
    print("\n[6] 护栏 C：步数上限")
    cap = 3
    original = settings.AGENT_MAX_STEPS
    settings.AGENT_MAX_STEPS = cap
    stub = _llm_factory(
        {
            SUPERVISOR_MARKER: ILLEGAL_TARGET_JSON,
            TOOL_MARKER: NO_TOOL_JSON,
        }
    )
    try:
        with patch.object(agent_dynamic, "get_llm", stub):
            result = _run(service, user_id)
    finally:
        settings.AGENT_MAX_STEPS = original

    steps = _steps_of(service, result["run_id"])
    _print_steps(steps)
    supervisor_steps = [s for s in steps if s.node_name == "supervisor"]
    capped = [s for s in _supervisor_summaries(steps) if "最大步数" in s]
    _record(
        f"达到步数上限 {cap} 即收尾",
        bool(capped) and len(supervisor_steps) <= cap + 1,
        f"supervisor 执行 {len(supervisor_steps)} 次，命中收尾 {len(capped)} 次，"
        f"状态={result['status']}",
    )


# ---------------------------------------------------------------------------
# 第 5 组：人工介入
# ---------------------------------------------------------------------------


def check_human_in_the_loop(service: MultiAgentService, user_id: int) -> None:
    """质检不通过且开了 HITL 时应暂停，带裁决值后可继续跑完。"""
    print("\n[7] 人工介入：暂停 → 裁决 → 继续")
    settings.AGENT_HITL_ENABLED = True
    stub = _llm_factory({REVIEWER_MARKER: REJECT_JSON})
    try:
        with patch.object(agent_service, "get_llm", stub):
            paused = _run(service, user_id)
            payload = paused.get("interrupt") or {}
            print(f"   run_id={paused['run_id']} status={paused['status']}")
            print(f"   interrupt={payload}")

            steps = _steps_of(service, paused["run_id"])
            _print_steps(steps)
            failed = [s for s in steps if s.status == "failed"]

            # 不带裁决值恢复：应原样返回待裁决内容，不重复跑
            again = service.resume(paused["run_id"])
            print(f"   无裁决值 resume -> status={again['status']}")

            # 带裁决值恢复：应继续跑完，答案为暂停时的那份草稿
            resumed = service.resume(paused["run_id"], decision="accept")
            print(
                f"   带裁决值 resume -> status={resumed['status']} "
                f"answer={resumed['final_answer'][:80]!r}"
            )
    finally:
        settings.AGENT_HITL_ENABLED = False

    _record(
        "质检不通过暂停为 awaiting_review",
        paused["status"] == "awaiting_review"
        and payload.get("type") == "review_rejected"
        and payload.get("options") == ["accept", "rewrite"],
        f"status={paused['status']}, interrupt.type={payload.get('type')}",
    )
    _record(
        "暂停不被当成节点失败",
        not failed,
        f"failed step 数={len(failed)}",
    )
    _record(
        "无裁决值时保持暂停不再重跑",
        again["status"] == "awaiting_review" and bool(again.get("interrupt")),
        f"status={again['status']}",
    )
    _record(
        "带裁决值可跑完且采纳草稿",
        resumed["status"] == "completed"
        and bool(resumed["final_answer"])
        and resumed["final_answer"] == payload.get("draft"),
        f"status={resumed['status']}，答案与草稿一致="
        f"{resumed['final_answer'] == payload.get('draft')}",
    )


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> int:
    """跑完全部验证项，返回进程退出码。"""
    user_id = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_USER_ID

    # 配置切换：同一份代码通过配置在确定性编排与动态编排之间切换
    settings.AGENT_ORCHESTRATION_MODE = "dynamic"
    settings.AGENT_MAX_STEPS = 12
    settings.AGENT_MAX_TOOL_CALLS = 3
    settings.AGENT_HITL_ENABLED = False

    print("=" * 72)
    print(f"动态编排与人工介入验证  user_id={user_id}")
    print(
        f"orchestration={settings.AGENT_ORCHESTRATION_MODE} "
        f"max_steps={settings.AGENT_MAX_STEPS} "
        f"max_tool_calls={settings.AGENT_MAX_TOOL_CALLS} "
        f"checkpoint={settings.AGENT_CHECKPOINT_BACKEND}"
    )
    print("=" * 72)

    check_ast_eval_safety()

    with SessionLocal() as session:
        session.rollback()
        service = MultiAgentService(session)
        check_dynamic_routing(service, user_id)
        check_guardrail_illegal_target(service, user_id)
        check_guardrail_no_progress(service, user_id)
        check_tool_ecosystem(service, user_id)
        check_guardrail_max_steps(service, user_id)
        check_human_in_the_loop(service, user_id)

    print("\n" + "=" * 72)
    passed = sum(1 for _, ok in RESULTS if ok)
    for name, ok in RESULTS:
        print(f"{'✅' if ok else '❌'} {name}")
    print(f"结果: {passed}/{len(RESULTS)} 项通过")
    print("=" * 72)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
