"""动态编排护栏的端到端回归测试。

supervisor 由模型驱动，可以点名任意工人节点。护栏早期只校验目标名是否在
VALID_TARGETS 内，不校验该目标的前置状态是否就绪，于是模型一旦跳过
planner / retriever 直接点名 generator 或 reviewer，节点就会读到
AgentState（TypedDict, total=False）里不存在的键而抛 KeyError，
整轮运行以 failed 收尾。

这组测试把敌意输出固化成回归：模型无论怎么乱点，运行都必须 completed，
且不产生任何 failed step。

测试不调真实模型、不连本地 Ollama：LLM 换成按提示词分流的假对象，
Embedding 换成固定向量，向量检索换成空结果，缓存由 conftest 的 autouse 夹具隔离。
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models import User
from app.repositories.vector_repository import VectorRepository
from app.services import agent_dynamic, agent_service
from app.services.agent_service import MultiAgentService

# supervisor 提示词的稳定标识，用来判断这次调用是不是 supervisor 在决策
SUPERVISOR_MARKER: str = "多 Agent 协作流程的调度员"

# 敌意输出：模型在开局就跳过前置节点，或给出越界目标、非 JSON、直接收尾
HOSTILE_SUPERVISOR_OUTPUTS: dict[str, str] = {
    "开局直接派 generator（跳过 planner 与 retriever）": '{"next": "generator", "reason": "直接生成"}',
    "开局直接派 reviewer（跳过 planner、retriever、generator）": '{"next": "reviewer", "reason": "直接审核"}',
    "开局直接派 retriever（跳过 planner）": '{"next": "retriever", "reason": "先检索"}',
    "开局直接派 tool": '{"next": "tool", "reason": "先调工具"}',
    "越界目标": '{"next": "system_admin", "reason": "越权"}',
    "输出非 JSON": "我认为应该先做任务规划，然后再检索文档。",
    "开局立即收尾": '{"next": "finish", "reason": "直接结束"}',
}


class _StubEmbeddings:
    """固定维度的假 Embedding，替代本地 Ollama 的 nomic-embed-text。"""

    def embed_query(self, text: str) -> list[float]:
        """返回固定维度零向量，检索结果的排序在测试里不重要。"""

        return [0.0] * settings.VECTOR_DIMENSION

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """按输入条数返回固定维度零向量。"""

        return [[0.0] * settings.VECTOR_DIMENSION for _ in texts]


def _stub_llm_factory(supervisor_payload: str) -> Any:
    """构造假 LLM 工厂：supervisor 决策返回指定 payload，其余调用返回固定文本。

    非 supervisor 的调用（planner / generator / reviewer / 工具规划）统一返回
    一段普通文本：planner 的 JSON 解析失败会退回原问题，reviewer 的 JSON 解析
    失败会判定通过并收尾，工具规划失败会判定为无需调用工具 —— 三条降级路径
    都是被测代码的既有行为，不需要模型配合。
    """

    def route(prompt_value: Any) -> AIMessage:
        if SUPERVISOR_MARKER in str(prompt_value):
            return AIMessage(content=supervisor_payload)
        return AIMessage(content="固定草稿答案")

    stub: RunnableLambda = RunnableLambda(route)
    return lambda: stub


@contextmanager
def _stubbed_environment(supervisor_payload: str) -> Iterator[None]:
    """把模型、Embedding 与向量检索整体替换为测试替身。"""

    with (
        patch.object(agent_service, "get_llm", _stub_llm_factory(supervisor_payload)),
        patch.object(agent_dynamic, "get_llm", _stub_llm_factory(supervisor_payload)),
        patch.object(agent_service, "get_embeddings", _StubEmbeddings),
        patch.object(VectorRepository, "search", lambda self, **kwargs: []),
    ):
        yield


def _run_dynamic(db: Session, user_id: int, payload: str) -> tuple[str, list[Any]]:
    """在 dynamic 模式下跑一轮，返回运行状态与步骤列表。"""

    with _stubbed_environment(payload):
        service = MultiAgentService(db)
        result: dict[str, Any] = service.run(
            user_id=user_id, session_id="orchestration", question="测试问题"
        )
        detail = service.get_run_detail(result["run_id"])

    assert detail is not None, "运行详情必须落库"
    return str(result["status"]), list(detail["steps"])


@pytest.mark.parametrize(
    "payload",
    list(HOSTILE_SUPERVISOR_OUTPUTS.values()),
    ids=list(HOSTILE_SUPERVISOR_OUTPUTS.keys()),
)
def test_hostile_supervisor_output_still_converges(
    db_session: Session,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
    payload: str,
) -> None:
    """模型无论怎么乱点，运行都必须 completed，且没有任何 failed step。"""

    monkeypatch.setattr(settings, "AGENT_ORCHESTRATION_MODE", "dynamic")

    status, steps = _run_dynamic(db_session, user.id, payload)

    assert status == "completed"
    assert steps, "至少要记录 supervisor 的步骤"
    failed = [s for s in steps if s.status == "failed"]
    assert failed == [], f"出现失败节点：{[(s.node_name, s.error_message) for s in failed]}"


def test_guardrail_redirects_early_generator_dispatch(
    db_session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """核心回归：前置未就绪时，护栏必须改走规则路径而不是放行。

    修复前 supervisor 会直接把控制权交给 generator，generator 下标读
    context_docs 抛 KeyError，运行 failed；修复后首步退回 planner。
    """

    monkeypatch.setattr(settings, "AGENT_ORCHESTRATION_MODE", "dynamic")

    status, steps = _run_dynamic(db_session, user.id, '{"next": "generator", "reason": "直接生成"}')

    assert status == "completed"
    nodes: list[str] = [s.node_name for s in steps]
    assert nodes[0] == "supervisor"
    assert "planner" in nodes, f"护栏必须改走规则路径，实际节点序列：{nodes}"
    assert nodes.index("planner") < nodes.index("generator")


def test_guardrail_redirects_early_reviewer_dispatch(
    db_session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同理：开局点名 reviewer 必须被改道，generator 必须排在 reviewer 之前。"""

    monkeypatch.setattr(settings, "AGENT_ORCHESTRATION_MODE", "dynamic")

    status, steps = _run_dynamic(db_session, user.id, '{"next": "reviewer", "reason": "直接审核"}')

    assert status == "completed"
    nodes: list[str] = [s.node_name for s in steps]
    assert "planner" in nodes
    assert "generator" in nodes
    assert nodes.index("planner") < nodes.index("reviewer")
    assert nodes.index("generator") < nodes.index("reviewer")


def test_supervisor_steps_are_persisted_with_zero_failures(
    db_session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """supervisor 自身每一步都要落库，且状态为 success，便于前端展示执行轨迹。"""

    monkeypatch.setattr(settings, "AGENT_ORCHESTRATION_MODE", "dynamic")

    status, steps = _run_dynamic(db_session, user.id, '{"next": "generator", "reason": "x"}')

    assert status == "completed"
    supervisor_steps = [s for s in steps if s.node_name == "supervisor"]
    assert supervisor_steps
    assert all(s.status == "success" for s in supervisor_steps)
    assert all(s.output_summary for s in supervisor_steps)
    assert any("回退规则路由" in (s.output_summary or "") for s in supervisor_steps), (
        "应当至少有一次护栏触发的记录，否则说明护栏没被走到"
    )


def test_deterministic_mode_still_runs_the_fixed_path(
    db_session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """确定性编排不受护栏改动影响：节点序列固定为 planner → retriever → generator → reviewer。"""

    monkeypatch.setattr(settings, "AGENT_ORCHESTRATION_MODE", "deterministic")

    status, steps = _run_dynamic(db_session, user.id, "{}")

    assert status == "completed"
    nodes: list[str] = [s.node_name for s in steps]
    assert nodes == ["planner", "retriever", "generator", "reviewer"]
