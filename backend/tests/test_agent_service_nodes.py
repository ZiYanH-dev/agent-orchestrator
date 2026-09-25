"""Agent 服务节点纯逻辑的单元测试。

这里只覆盖不触达数据库与模型的部分：Planner 输出规整、以及两条条件路由。
被调用的是实例方法，但它们都不读 self 的字段，因此用 __new__ 绕开 __init__，
避免为了测一个纯函数而去建库、连 LLM。
"""
from __future__ import annotations

from typing import Any

import pytest
from langgraph.graph import END

from app.services.agent_service import MultiAgentService

# 不调用 __init__，直接拿一个可用实例；这些方法本身不依赖实例状态
_service: MultiAgentService = MultiAgentService.__new__(MultiAgentService)


# ---------------------------------------------------------------------------
# Planner 输出规整
# ---------------------------------------------------------------------------

def test_normalize_plain_string_list() -> None:
    """标准输出：字符串数组原样保留。"""

    result: list[str] = MultiAgentService._normalize_sub_tasks(
        ["第一个子问题", "第二个子问题"], "原问题"
    )

    assert result == ["第一个子问题", "第二个子问题"]


def test_normalize_truncates_to_three() -> None:
    """超过 3 个子问题时只保留前 3 个，避免检索轮数失控。"""

    result: list[str] = MultiAgentService._normalize_sub_tasks(
        ["a", "b", "c", "d", "e"], "原问题"
    )

    assert result == ["a", "b", "c"]


def test_normalize_object_list_takes_first_string_value() -> None:
    """对象数组是模型常见的跑偏形态，取每个对象里第一个字符串值。"""

    parsed = [
        {"question": "子问题一", "target": "文档"},
        {"sub_question": "子问题二"},
    ]

    assert MultiAgentService._normalize_sub_tasks(parsed, "原问题") == [
        "子问题一",
        "子问题二",
    ]


@pytest.mark.parametrize("key", ["sub_tasks", "sub_questions"])
def test_normalize_unwraps_nested_container(key: str) -> None:
    """被包成 {"sub_tasks": [...]} 时先拆壳再规整。"""

    parsed = {key: ["拆出来的子问题"]}

    assert MultiAgentService._normalize_sub_tasks(parsed, "原问题") == ["拆出来的子问题"]


@pytest.mark.parametrize(
    "parsed",
    [None, 42, "不是数组", {}, {"sub_tasks": "不是数组"}, []],
)
def test_normalize_falls_back_to_original_question(parsed: object) -> None:
    """拿不到任何有效子任务时退回原问题，保证后续检索仍有输入。"""

    assert MultiAgentService._normalize_sub_tasks(parsed, "原问题") == ["原问题"]


def test_normalize_drops_blank_items() -> None:
    """纯空白项被过滤；全部过滤掉时同样退回原问题。"""

    assert MultiAgentService._normalize_sub_tasks(["  ", "有效问题"], "原问题") == [
        "有效问题"
    ]
    assert MultiAgentService._normalize_sub_tasks(["  ", ""], "原问题") == ["原问题"]


def test_normalize_strips_whitespace() -> None:
    """子问题两侧空白被清理。"""

    assert MultiAgentService._normalize_sub_tasks(["  带空格的子问题  "], "原问题") == [
        "带空格的子问题"
    ]


def test_normalize_truncates_before_type_filtering() -> None:
    """先取前 3 项再逐项过滤，因此混入的非法元素只会让有效项变少。

    数组里混入非字符串非对象元素时跳过，不影响其他有效项；同时验证截断发生在
    过滤之前 —— 第 4 项之后的对象不会被读到。
    """

    parsed = ["有效", 123, None, {"q": "第 4 项，不该被读到"}]

    assert MultiAgentService._normalize_sub_tasks(parsed, "原问题") == ["有效"]


def test_normalize_keeps_object_inside_first_three() -> None:
    """前 3 项里的对象元素会被取成字符串，与字符串元素混排也能保留。"""

    parsed = ["纯字符串", {"question": "对象里的问题"}, ["嵌套数组", "忽略"]]

    assert MultiAgentService._normalize_sub_tasks(parsed, "原问题") == [
        "纯字符串",
        "对象里的问题",
    ]


def test_normalize_all_invalid_falls_back_to_question() -> None:
    """前 3 项全部无效时退回原问题，保证检索阶段仍有输入。"""

    assert MultiAgentService._normalize_sub_tasks([123, None, []], "原问题") == ["原问题"]


# ---------------------------------------------------------------------------
# 条件路由
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("current_task_index", "expected"),
    [(0, "retriever"), (1, "retriever"), (2, "generator"), (5, "generator")],
)
def test_route_after_retriever(current_task_index: int, expected: str) -> None:
    """还有子任务未检索就继续检索，全部检索完才进 Generator。"""

    state = {
        "sub_tasks": ["a", "b"],
        "current_task_index": current_task_index,
    }

    assert _service._route_after_retriever(state) == expected


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"final_answer": "答案"}, END),
        ({"retry_count": 3, "max_retry": 3}, END),
        ({"retry_count": 4, "max_retry": 3}, END),
        ({"retry_count": 1, "max_retry": 3}, "generator"),
        ({"retry_count": 0, "max_retry": 3}, "generator"),
        ({}, "generator"),
    ],
)
def test_route_after_reviewer(state: dict[str, Any], expected: str) -> None:
    """质检通过或重试耗尽就收尾，否则回到 Generator 重写。"""

    assert _service._route_after_reviewer(state) == expected
