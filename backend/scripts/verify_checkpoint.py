"""验证 LangGraph Checkpoint + Recovery 核心逻辑。

用 MemorySaver（langgraph 内置，无需外部依赖）验证：
1. 多节点图每个节点执行完自动 checkpoint
2. 中间节点因外部依赖故障（用全局计数器模拟 LLM 超时）
3. 恢复时外部依赖已恢复 → 节点正常执行 → 状态继续推进
"""
from __future__ import annotations

import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict


class TestState(TypedDict):
    """测试用共享状态。"""

    count: int
    results: list[str]
    last_node: str


# 模拟"外部依赖故障计数器"——前 2 次调用 step_b 时，LLM 超时
# 第 3 次调用时，LLM 恢复可用
_llm_call_count = {"b": 0}


def step_a(state: TestState) -> TestState:
    """节点 A。"""

    print(f"  [Step A] ✅ 执行中, count={state['count']}")
    return {
        "count": state["count"] + 1,
        "results": [*state["results"], "A"],
        "last_node": "A",
    }


def step_b(state: TestState) -> TestState:
    """节点 B — 模拟 LLM 前 2 次超时，第 3 次成功。"""

    _llm_call_count["b"] += 1
    call_num = _llm_call_count["b"]
    print(f"  [Step B] 调用 LLM（第 {call_num} 次）, count={state['count']}")

    if call_num <= 2:
        print(f"  [Step B] 💥 LLM 超时！（故障 #{call_num}）")
        raise RuntimeError(f"LLM 超时: attempt {call_num}")

    print("  [Step B] ✅ LLM 终于返回了")
    return {
        "count": state["count"] + 1,
        "results": [*state["results"], "B"],
        "last_node": "B",
    }


def step_c(state: TestState) -> TestState:
    """节点 C。"""

    print(f"  [Step C] ✅ 执行中, count={state['count']}")
    return {
        "count": state["count"] + 1,
        "results": [*state["results"], "C"],
        "last_node": "C",
    }


def build_graph(checkpointer: MemorySaver):
    """构建带 checkpoint 的状态图。"""

    graph = StateGraph(TestState)
    graph.add_node("step_a", step_a)
    graph.add_node("step_b", step_b)
    graph.add_node("step_c", step_c)
    graph.add_edge(START, "step_a")
    graph.add_edge("step_a", "step_b")
    graph.add_edge("step_b", "step_c")
    graph.add_edge("step_c", END)
    return graph.compile(checkpointer=checkpointer)


def main() -> None:
    global _llm_call_count
    _llm_call_count = {"b": 0}  # 重置故障计数器

    print("=" * 60)
    print("【验证】故障恢复 — 外部依赖（LLM）故障后恢复")
    print("=" * 60)
    print("  场景：step_b 调用 LLM，前 2 次超时，第 3 次成功")
    print("  验证：每次故障后 checkpoint 都保存了 step_a 的好状态")
    print("        恢复时从 checkpoint 继续，step_b 重新执行 → 计数器 +1 → 直到成功")
    print()

    saver = MemorySaver()
    graph = build_graph(saver)
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial = {"count": 0, "results": [], "last_node": ""}

    # ---- 第 1 次：step_a 成功，step_b 故障 #1 ----
    print("  🔄 Run #1 — 首次执行")
    try:
        graph.invoke(initial, config)
    except RuntimeError as e:
        print(f"  💥 故障 #1: {e}")

    cps = list(saver.list(config))
    print(f"  📝 checkpoint 数: {len(cps)}")
    print(f"  📍 最近好状态: count={cps[0].checkpoint['channel_values'].get('count')}, "
          f"results={cps[0].checkpoint['channel_values'].get('results')}")
    print()

    # ---- 恢复 #1：从最近 checkpoint 继续，step_b 还是故障 #2 ----
    print("  🔄 Run #2 — 恢复（LLM 还没恢复）")
    try:
        graph.invoke(None, config)  # None = 从 checkpoint 恢复
    except RuntimeError as e:
        print(f"  💥 故障 #2: {e}")

    print()

    # ---- 恢复 #2：step_b 第 3 次调用，成功！→ step_c → END ----
    print("  🔄 Run #3 — 恢复（LLM 恢复了！）")
    final = graph.invoke(None, config)

    print()
    print("  ✅ 最终结果:")
    print(f"     count={final['count']}  results={final['results']}  last_node={final['last_node']}")

    cps_final = list(saver.list(config))
    print(f"  📝 总 checkpoint 数: {len(cps_final)}")
    for i, cp in enumerate(cps_final):
        vals = cp.checkpoint["channel_values"]
        print(f"     [{i}] count={vals.get('count')}, results={vals.get('results')}, "
              f"last_node={vals.get('last_node')}")

    # 断言
    assert final["count"] == 3, f"预期 count=3, 实际={final['count']}"
    assert final["results"] == ["A", "B", "C"], \
        f"预期 results=['A','B','C'], 实际={final['results']}"
    # START 快照 + step_a + step_b + step_c + END = 5 个
    assert len(cps_final) == 5, f"预期 5 个 checkpoint, 实际={len(cps_final)}"

    print()
    print("  🎉 所有断言通过！")
    print("     ✅ 每个节点执行完自动 checkpoint")
    print("     ✅ 故障后最近好状态完整保留")
    print("     ✅ 恢复时从最近 checkpoint 继续执行")
    print("     ✅ 状态正确推进，最终结果正确")

    print()
    print("=" * 60)
    print("LangGraph Checkpoint + Recovery 验证完成 ✅")
    print("=" * 60)


if __name__ == "__main__":
    main()
