"""动态编排模块的纯逻辑单元测试。

覆盖三块不依赖模型与数据库的逻辑：
  1. 工具生态 —— AST 白名单求值与上下文统计；
  2. supervisor 决策输入 —— 阶段状态摘要与进展指纹；
  3. 六层护栏 —— 前置状态校验与规则兜底路由。

第 3 块是本文件的重点：护栏早期只校验目标名是否在白名单内，不校验该目标的
前置状态是否就绪，导致模型跳过前置节点直接点名下游时节点抛 KeyError。
下面用「可达状态不变量」把这条修复钉死。
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from langgraph.graph import END

from app.services.agent_dynamic import (
    TOOL_REGISTRY,
    VALID_TARGETS,
    ExpressionError,
    _eval_expr,
    _prerequisites_met,
    _progress_digest,
    _progress_key,
    rule_based_route,
    tool_calculate,
    tool_context_stats,
)
from app.services.agent_service import AgentState


def _state(**fields: Any) -> AgentState:
    """构造一个总可缺键的 AgentState，省去每处重复标注类型。"""

    return AgentState(**fields)


# ---------------------------------------------------------------------------
# 工具生态：AST 白名单求值
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1+1", "1+1 = 2"),
        ("120 * 0.85", "120 * 0.85 = 102"),
        ("2 ** 10", "2 ** 10 = 1024"),
        ("7 // 2", "7 // 2 = 3"),
        ("7 % 3", "7 % 3 = 1"),
        ("-(3+4)", "-(3+4) = -7"),
        ("(1 + 2) * 3", "(1 + 2) * 3 = 9"),
    ],
)
def test_tool_calculate_evaluates_arithmetic(expression: str, expected: str) -> None:
    """白名单内的算术表达式应求值成功并回显原式与结果。"""

    assert tool_calculate({"expression": expression}, _state()) == expected


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo hi')",
        "open('/etc/passwd').read()",
        "(1).__class__.__mro__",
        "lambda: 1",
        "[1, 2, 3]",
        "1 if True else 2",
        "'abc'",
        "a + b",
        "True",
        "1 +",
        "1 / 0",
    ],
)
def test_tool_calculate_rejects_non_arithmetic(expression: str) -> None:
    """含调用、属性访问、推导式、变量名、字符串与除零的输入一律拒绝，不向上抛异常。"""

    result: str = tool_calculate({"expression": expression}, _state())
    assert result.startswith("计算失败")


def test_tool_calculate_does_not_execute_code(tmp_path: Path) -> None:
    """表达式里的副作用必须没有发生：文件不应被创建。"""

    marker: Path = tmp_path / "pwned"
    expression: str = f"__import__('pathlib').Path('{marker}').write_text('x')"

    result: str = tool_calculate({"expression": expression}, _state())

    assert result.startswith("计算失败")
    assert not marker.exists()


def test_tool_calculate_requires_expression() -> None:
    """缺少 expression 参数时给出明确提示。"""

    assert tool_calculate({}, _state()) == "calculate 缺少 expression 参数"
    assert tool_calculate({"expression": "   "}, _state()) == "calculate 缺少 expression 参数"


@pytest.mark.parametrize(
    "source",
    [
        "foo(1)",
        "(1).real",
        "lambda x: x",
        "1 if x else 2",
        "[1, 2]",
        "x + 1",
        "{'a': 1}",
    ],
)
def test_eval_expr_rejects_disallowed_ast_nodes(source: str) -> None:
    """AST 白名单之外的所有节点类型都必须抛 ExpressionError。"""

    with pytest.raises(ExpressionError):
        _eval_expr(ast.parse(source, mode="eval").body)


# ---------------------------------------------------------------------------
# 工具生态：上下文统计
# ---------------------------------------------------------------------------

def test_tool_context_stats_without_docs() -> None:
    """没有检索结果时给出可读的空状态。"""

    assert tool_context_stats({}, _state()) == "当前没有已检索的上下文片段"


def test_tool_context_stats_reports_count_and_score_range() -> None:
    """统计片段数、来源文档数与最高最低分。"""

    state = _state(
        context_docs=[
            {"content": "a", "document_id": 7, "score": 0.9},
            {"content": "b", "document_id": 7, "score": 0.5},
            {"content": "c", "document_id": 9, "score": 0.7},
        ]
    )

    result: str = tool_context_stats({}, state)

    assert "已检索片段 3 个" in result
    assert "来自 2 篇文档" in result
    assert "最高分 0.900" in result
    assert "最低分 0.500" in result


def test_tool_context_stats_tolerates_missing_score() -> None:
    """score 缺失或为 None 时按 0 处理，不抛异常。"""

    state = _state(context_docs=[{"content": "a", "document_id": 1}, {"content": "b", "score": None}])

    assert "最高分 0.000" in tool_context_stats({}, state)


def test_tool_registry_matches_valid_targets() -> None:
    """工具表的键必须与白名单里的 tool 目标一致，否则 supervisor 派发必失败。"""

    assert set(TOOL_REGISTRY) == {"calculate", "context_stats"}
    assert VALID_TARGETS == frozenset(
        {"planner", "retriever", "generator", "reviewer", "tool"}
    )


# ---------------------------------------------------------------------------
# supervisor 决策输入
# ---------------------------------------------------------------------------

def test_progress_digest_on_fresh_state() -> None:
    """开局时四个阶段都报「未开始」。"""

    digest: str = _progress_digest(_state())

    assert "- 问题拆解: 未开始" in digest
    assert "- 文档检索: 未开始" in digest
    assert "- 回答草稿: 未开始" in digest
    assert "- 质量审核: 未开始" in digest


def test_progress_digest_while_retrieving() -> None:
    """拆解完成但子任务未检索完时，文档检索报「进行中」并带进度数字。"""

    digest: str = _progress_digest(
        _state(sub_tasks=["a", "b"], current_task_index=1, context_docs=[{"content": "x"}])
    )

    assert "已完成，共 2 个子问题" in digest
    assert "进行中，2 个子问题已检索 1 个" in digest


def test_progress_digest_after_retrieval_done() -> None:
    """检索全部完成时报「已完成」并给出片段总数。"""

    digest: str = _progress_digest(
        _state(sub_tasks=["a"], current_task_index=1, context_docs=[{"content": "x"}])
    )

    assert "已完成，1 个子问题全部检索完，共 1 条片段" in digest


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"review_feedback": "太空泛"}, "- 质量审核: 不通过"),
        ({"final_answer": "答案"}, "- 质量审核: 已通过"),
        ({}, "- 质量审核: 未开始"),
    ],
)
def test_progress_digest_review_stage(fields: dict[str, Any], expected: str) -> None:
    """审核阶段按 final_answer / review_feedback 的取值映射成三种状态。"""

    assert expected in _progress_digest(_state(**fields))


def test_progress_key_ignores_step_count() -> None:
    """进展指纹刻意不含步数：步数每轮递增，算进来就永远识别不出原地打转。"""

    base: dict[str, Any] = {"sub_tasks": ["a"], "current_task_index": 0}
    first: str = _progress_key(_state(**base, step_count=1))
    later: str = _progress_key(_state(**base, step_count=9))

    assert first == later


@pytest.mark.parametrize(
    "changed",
    [
        {"sub_tasks": ["a", "b"]},
        {"current_task_index": 1},
        {"context_docs": [{"content": "x"}]},
        {"tool_trace": [{"tool": "calculate"}]},
        {"draft_answer": "草稿"},
        {"final_answer": "答案"},
        {"review_feedback": "改进建议"},
        {"retry_count": 1},
    ],
)
def test_progress_key_changes_with_real_progress(changed: dict[str, Any]) -> None:
    """任一维度的实质进展变化都必须改变指纹。"""

    baseline: dict[str, Any] = {
        "sub_tasks": ["a"],
        "current_task_index": 0,
        "context_docs": [],
        "tool_trace": [],
        "retry_count": 0,
    }
    assert _progress_key(_state(**baseline)) != _progress_key(
        _state(**{**baseline, **changed})
    )


# ---------------------------------------------------------------------------
# 护栏三：前置状态校验（P0 修复的回归）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (_state(), False),
        (_state(sub_tasks=[]), False),
        (_state(sub_tasks=["a"], current_task_index=0), True),
        (_state(sub_tasks=["a"], current_task_index=1), False),
        (_state(sub_tasks=["a", "b"], current_task_index=1), True),
        (_state(sub_tasks=["a", "b"], current_task_index=2), False),
    ],
)
def test_retriever_prerequisites(state: AgentState, expected: bool) -> None:
    """retriever 读 sub_tasks 与 current_task_index，两者缺一都会崩。"""

    assert _prerequisites_met("retriever", state) is expected


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (_state(), False),
        (_state(context_docs=[]), True),
        (_state(context_docs=[{"content": "x"}]), True),
    ],
)
def test_generator_prerequisites(state: AgentState, expected: bool) -> None:
    """generator 直接下标读 context_docs，键不存在即 KeyError，空列表则安全。"""

    assert _prerequisites_met("generator", state) is expected


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (_state(), False),
        (_state(draft_answer=""), True),
        (_state(draft_answer="草稿"), True),
    ],
)
def test_reviewer_prerequisites(state: AgentState, expected: bool) -> None:
    """reviewer 下标读 draft_answer，键不存在即 KeyError。"""

    assert _prerequisites_met("reviewer", state) is expected


@pytest.mark.parametrize("target", ["planner", "tool"])
def test_planner_and_tool_need_no_prerequisites(target: str) -> None:
    """planner 是入口节点，tool 只读 question，两者对前置状态没有要求。"""

    assert _prerequisites_met(target, _state()) is True


# ---------------------------------------------------------------------------
# 护栏三配套：规则兜底路由
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (_state(final_answer="答案"), END),
        (_state(), "planner"),
        (_state(sub_tasks=["a"]), "retriever"),
        (_state(sub_tasks=["a"], current_task_index=1), "generator"),
        (
            _state(
                sub_tasks=["a"],
                current_task_index=1,
                draft_answer="草稿",
                review_feedback="改一下",
                retry_count=1,
            ),
            "generator",
        ),
        (
            _state(
                sub_tasks=["a"],
                current_task_index=1,
                draft_answer="草稿",
                review_feedback="改一下",
                retry_count=3,
                max_retry=3,
            ),
            END,
        ),
        (_state(sub_tasks=["a"], current_task_index=1, draft_answer="草稿"), "reviewer"),
    ],
)
def test_rule_based_route_full_branch_coverage(
    state: AgentState, expected: str
) -> None:
    """规则路由的每一个分支都要走到：收尾、拆解、检索、生成、重试、重试耗尽、审核。"""

    assert rule_based_route(state) == expected


# 只列出图运行时真实可能出现的状态：每个键都由某个节点的返回值写入。
_REACHABLE_STATES: list[AgentState] = [
    _state(),
    _state(question="q", user_id=1, run_id="r", max_retry=3),
    _state(sub_tasks=["a"], current_task_index=0, context_docs=[]),
    _state(
        sub_tasks=["a"],
        current_task_index=1,
        context_docs=[{"content": "x", "document_id": 1, "score": 0.9}],
    ),
    _state(
        sub_tasks=["a"],
        current_task_index=1,
        context_docs=[{"content": "x"}],
        draft_answer="草稿",
    ),
    _state(
        sub_tasks=["a"],
        current_task_index=1,
        context_docs=[{"content": "x"}],
        draft_answer="草稿",
        review_feedback="太短",
        retry_count=1,
    ),
    _state(
        sub_tasks=["a"],
        current_task_index=1,
        context_docs=[{"content": "x"}],
        draft_answer="草稿",
        review_feedback="太短",
        retry_count=3,
        max_retry=3,
    ),
    _state(
        sub_tasks=["a"],
        current_task_index=1,
        context_docs=[{"content": "x"}],
        draft_answer="草稿",
        final_answer="草稿",
    ),
]


@pytest.mark.parametrize(
    "state", _REACHABLE_STATES, ids=[str(i) for i in range(len(_REACHABLE_STATES))]
)
def test_fallback_target_always_has_prerequisites_ready(state: AgentState) -> None:
    """护栏回退后落到的新目标，其前置状态必须已就绪。

    这是「图一定收敛」的核心不变量：supervisor 先按白名单与前置状态筛掉不可用
    的目标，再退回规则路径；如果规则路径给出的目标自身前置也未就绪，节点照样会
    抛 KeyError，护栏就等于没兜住。因此这里逐一验证可达状态。
    """

    for target in VALID_TARGETS:
        if _prerequisites_met(target, state):
            continue
        fallback: str = rule_based_route(state)
        assert fallback == END or _prerequisites_met(fallback, state), (
            f"状态 {state} 下目标 {target} 前置未就绪，回退到 {fallback} 后依然未就绪"
        )


@pytest.mark.parametrize(
    "state", _REACHABLE_STATES, ids=[str(i) for i in range(len(_REACHABLE_STATES))]
)
def test_rule_based_route_only_returns_legal_nodes(state: AgentState) -> None:
    """规则路由不得返回白名单之外的节点名。"""

    assert rule_based_route(state) in VALID_TARGETS | {END}
