"""多 Agent 协作服务层。

架构：
  Planner Agent  →  Retriever Agent  →  Generator Agent  ⇄  Reviewer Agent
  (拆问题)          (检索文档)          (生成回答)          (质检+循环)

每个子图节点执行完自动 checkpoint，故障后可从最近 checkpoint 恢复。
节点执行日志自动落库到 agent_steps 表。
"""
from __future__ import annotations

import json
import uuid
from typing import Any, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt
from sqlalchemy.orm import Session
from typing_extensions import TypedDict

from app.config.embeddings_client import get_embeddings
from app.config.llm_client import get_llm
from app.config.settings import settings
from app.core.cache import RETRIEVAL_TTL_SECONDS, cache, retrieval_key
from app.core.logging import logger
from app.repositories.agent_run_repository import AgentRunRepository
from app.repositories.agent_step_repository import AgentStepRepository
from app.repositories.vector_repository import VectorRepository

# ---------------------------------------------------------------------------
# 共享状态 Schema
# ---------------------------------------------------------------------------

class AgentState(TypedDict, total=False):
    """多 Agent 共享状态（LangGraph 各节点读写）。"""

    question: str
    sub_tasks: list[str]
    current_task_index: int
    context_docs: list[dict]  # [{content, document_id, score}]
    draft_answer: str
    final_answer: str
    review_feedback: str
    retry_count: int
    max_retry: int
    user_id: int
    run_id: str
    # 动态编排使用：步数用于护栏控制，工具轨迹记录每次工具调用
    step_count: int
    tool_trace: list[dict]
    # 动态编排护栏用：上一次派发目标，以及当时的实质进展指纹
    last_target: str
    last_progress_key: str


# ---------------------------------------------------------------------------
# Agent 服务主类（节点作为方法，自动落库 step 日志）
# ---------------------------------------------------------------------------

class MultiAgentService:
    """多 Agent 协作服务。

    使用方式：
        service = MultiAgentService(db_session)
        result = service.run(user_id=1, session_id="default", question="...")
        # 恢复：
        result = service.resume(run_id="xxx")
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._run_repo = AgentRunRepository(session)
        self._step_repo = AgentStepRepository(session)
        self._vector_repo = VectorRepository(session)
        self._graph = self._build_graph()

    # ------------------------------------------------------------------
    # 图构建
    # ------------------------------------------------------------------

    def _build_graph(self) -> CompiledStateGraph:
        """构建 LangGraph 主图。

        编排模式由 settings.AGENT_ORCHESTRATION_MODE 决定：deterministic 走四节点
        固定图，路径由代码定义；dynamic 走 supervisor 动态路由，路径由模型决定。
        两种模式共用同一批节点实现，区别只在连线方式。
        """
        from app.config.checkpoint import get_checkpointer

        checkpointer = get_checkpointer()

        if settings.AGENT_ORCHESTRATION_MODE == "dynamic":
            # 延迟导入，避免与 agent_dynamic 形成循环依赖
            from app.services.agent_dynamic import build_dynamic_graph

            logger.info("agent orchestration mode: dynamic")
            return build_dynamic_graph(self, checkpointer)

        graph = StateGraph(AgentState)

        # 节点（类方法，内部自动记录 step 日志）
        graph.add_node("planner", self._planner_node)
        graph.add_node("retriever", self._retriever_node)
        graph.add_node("generator", self._generator_node)
        graph.add_node("reviewer", self._reviewer_node)

        # 边
        graph.add_edge(START, "planner")
        graph.add_edge("planner", "retriever")
        graph.add_conditional_edges("retriever", self._route_after_retriever, {
            "retriever": "retriever",
            "generator": "generator",
        })
        graph.add_edge("generator", "reviewer")
        graph.add_conditional_edges("reviewer", self._route_after_reviewer, {
            "generator": "generator",
            END: END,
        })

        return graph.compile(checkpointer=checkpointer)

    # ------------------------------------------------------------------
    # 节点日志辅助方法
    # ------------------------------------------------------------------

    def _record_step_start(
        self, run_id: str, node_name: str, input_summary: str = ""
    ) -> int:
        """记录 step 开始，返回 step_id。"""
        existing = self._step_repo.list_by_run(run_id)
        same_node = [s for s in existing if s.node_name == node_name]
        attempt = len(same_node) + 1

        step = self._step_repo.create(
            run_id=run_id,
            node_name=node_name,
            attempt=attempt,
            input_summary=input_summary[:500],
        )
        self._session.commit()

        # 更新 run 状态
        status_map = {
            "planner": "planning",
            "retriever": "retrieving",
            "generator": "generating",
            "reviewer": "reviewing",
        }
        self._run_repo.update_status(run_id, status=status_map.get(node_name, "running"))
        self._session.commit()

        return step.id

    def _record_step_done(
        self, step_id: int, status: str, output_summary: str = "", error: str | None = None
    ) -> None:
        """记录 step 完成。"""
        self._step_repo.complete(
            step_id,
            status=status,
            output_summary=output_summary[:500] if output_summary else None,
            error_message=error[:1000] if error else None,
        )
        self._session.commit()

    def _record_step_failed(self, run_id: str, node_name: str, error: str) -> None:
        """标记最近一个失败的 step。"""
        steps = self._step_repo.list_by_run(run_id)
        # 找最后一个 running 的同节点 step（就是刚失败的那个）
        for step in reversed(steps):
            if step.node_name == node_name and step.status == "running":
                self._step_repo.complete(
                    step.id, status="failed", error_message=error[:1000]
                )
                break
        self._run_repo.update_status(
            run_id,
            status="failed",
            retry_count=len([s for s in steps if s.status == "failed"]),
        )
        self._session.commit()

    # ------------------------------------------------------------------
    # 各 Agent 节点（内部自动记录 step 日志）
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_sub_tasks(parsed: object, question: str) -> list[str]:
        """把 Planner 返回的拆解结果规整为 1-3 个非空字符串子任务。

        LLM 输出不稳定，可能出现三种情况，都必须收敛成字符串列表：
        对象数组 [{...}]、被包成 {"sub_tasks": [...]}、或直接不是合法 JSON。
        收不到任何有效子任务时退回原问题。
        """
        if isinstance(parsed, dict):
            parsed = parsed.get("sub_tasks") or parsed.get("sub_questions")

        if not isinstance(parsed, list):
            return [question]

        tasks: list[str] = []
        for item in parsed[:3]:
            if isinstance(item, str):
                text = item.strip()
            elif isinstance(item, dict):
                text = next(
                    (v.strip() for v in item.values() if isinstance(v, str)), ""
                )
            else:
                text = ""
            if text:
                tasks.append(text)

        return tasks or [question]

    def _planner_node(self, state: AgentState) -> AgentState:
        """Planner Agent：将用户问题拆解为 1-3 个可检索的子任务。"""
        run_id = state["run_id"]
        step_id = self._record_step_start(
            run_id, "planner", f"question: {state['question'][:200]}"
        )

        try:
            llm: BaseChatModel = get_llm()
            prompt = ChatPromptTemplate.from_template(
                """你是一个任务拆解专家。将下面的用户问题拆解为 1-3 个可以独立检索的子问题，以便后续检索增强生成。

要求：
- 子问题要具体，每个子问题对应一个明确的检索目标
- 如果原问题已经很具体了，只拆 1 个
- 用 JSON 数组格式返回，不要有其他内容

问题：{question}

子问题："""
            )
            chain = prompt | llm | StrOutputParser()
            raw = chain.invoke({"question": state["question"]})

            try:
                parsed: object = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None

            sub_tasks = self._normalize_sub_tasks(parsed, state["question"])

            # 动态编排下 Planner 可能被重复派发。重复派发时若照旧清零
            # current_task_index 与 context_docs，已检索到的片段会白丢，进展指纹
            # 也会来回抖动，原地打转的检测随之失效。因此只有拆解数量变化、
            # 也就是真的换了拆法时才重置检索进度。
            update: AgentState = {"sub_tasks": sub_tasks}
            replayed = len(sub_tasks) == len(state.get("sub_tasks", []))
            if not replayed:
                update["current_task_index"] = 0
                update["context_docs"] = []

            self._record_step_done(
                step_id,
                "success",
                f"sub_tasks={len(sub_tasks)}"
                + ("（沿用原有检索进度）" if replayed else ""),
            )

            return update

        # 记录节点失败后向上抛出，由上层统一落库为 failed
        except Exception as e:
            self._record_step_failed(run_id, "planner", str(e))
            raise

    def _retriever_node(self, state: AgentState) -> AgentState:
        """Retriever Agent：对当前子任务检索相关文档片段。"""
        run_id = state["run_id"]
        current_idx = state["current_task_index"]
        total_tasks = len(state["sub_tasks"])
        step_id = self._record_step_start(
            run_id, "retriever",
            f"task {current_idx + 1}/{total_tasks}: {state['sub_tasks'][current_idx][:100] if current_idx < total_tasks else ''}"
        )

        try:
            current_task = state["sub_tasks"][current_idx]
            user_id = state["user_id"]
            new_docs: list[dict] = []

            # 同一子任务可能被重复拆出，跨运行也可能重复提问，命中缓存可省去向量化与查询
            cache_key: str = retrieval_key(user_id, current_task)
            cached_docs = cache.get_json(cache_key)

            if cached_docs is not None:
                logger.info("retrieval cache hit, user_id=%s", user_id)
                new_docs = cached_docs
            else:
                embeddings = get_embeddings()
                query_vector = embeddings.embed_query(current_task)

                rows = self._vector_repo.search(
                    user_id=user_id,
                    query_vector=query_vector,
                    top_k=settings.RETRIEVE_TOP_K,
                )

                for _chunk_id, doc_id, chunk_index, content, score in rows:
                    new_docs.append({
                        "content": content,
                        "document_id": doc_id,
                        "chunk_index": chunk_index,
                        "score": score,
                    })

                cache.set_json(cache_key, new_docs, RETRIEVAL_TTL_SECONDS)

            existing = state.get("context_docs", [])
            merged = existing + new_docs

            self._record_step_done(
                step_id, "success", f"got {len(new_docs)} docs"
            )

            return {
                "context_docs": merged,
                "current_task_index": current_idx + 1,
            }

        # 记录节点失败后向上抛出，由上层统一落库为 failed
        except Exception as e:
            self._record_step_failed(run_id, "retriever", str(e))
            raise

    def _generator_node(self, state: AgentState) -> AgentState:
        """Generator Agent：基于检索到的文档生成回答草稿。"""
        run_id = state["run_id"]
        step_id = self._record_step_start(
            run_id, "generator",
            f"docs={len(state.get('context_docs', []))}, feedback={bool(state.get('review_feedback'))}"
        )

        try:
            llm: BaseChatModel = get_llm()
            docs = state["context_docs"]
            context_text = "\n\n".join(doc["content"] for doc in docs) if docs else "（无相关文档）"

            prompt = ChatPromptTemplate.from_template(
                """请基于以下检索到的文档内容，回答用户的问题。

规则：
- 优先使用文档中的信息
- 如果文档中没有相关信息，请回答"根据现有资料无法回答该问题"
- 不要编造文档里没有的内容

检索到的文档：
{context}

用户问题：{question}

之前 Reviewer 的反馈（如果有）：
{feedback}

请生成回答："""
            )
            chain = prompt | llm | StrOutputParser()
            draft = chain.invoke({
                "context": context_text,
                "question": state["question"],
                "feedback": state.get("review_feedback", "无"),
            })

            self._record_step_done(step_id, "success", draft[:200])

            return {"draft_answer": draft}

        # 记录节点失败后向上抛出，由上层统一落库为 failed
        except Exception as e:
            self._record_step_failed(run_id, "generator", str(e))
            raise

    def _reviewer_node(self, state: AgentState) -> AgentState:
        """Reviewer Agent：检查回答质量，不通过则返回 feedback 让 Generator 重试。"""
        run_id = state["run_id"]
        step_id = self._record_step_start(
            run_id, "reviewer",
            f"retry={state.get('retry_count', 0)}/{state.get('max_retry', 3)}"
        )

        try:
            llm: BaseChatModel = get_llm()
            docs = state["context_docs"]
            context_text = "\n\n".join(doc["content"] for doc in docs) if docs else ""

            prompt = ChatPromptTemplate.from_template(
                """你是一个回答质量审核专家。检查下面的回答是否合格。

合格标准：
1. 回答与用户问题相关，不跑题
2. 如果检索到了文档，回答应基于文档内容（可以不完全照搬）
3. 不要有明显的幻觉（编造文档中没有的信息）
4. 语言通顺、逻辑清晰

用户问题：{question}

检索到的文档（参考用）：
{context}

待审核回答：
{answer}

请只返回 JSON 格式：
{{"passed": true 或 false, "feedback": "如果 passed=false，这里写改进建议；如果 passed=true，这里留空"}}
"""
            )
            chain = prompt | llm | StrOutputParser()
            raw = chain.invoke({
                "question": state["question"],
                "context": context_text[:3000],
                "answer": state["draft_answer"],
            })

            try:
                result = json.loads(raw)
                passed = result.get("passed", True)
                feedback = result.get("feedback", "")
            except json.JSONDecodeError:
                passed = True
                feedback = ""

            if passed:
                self._record_step_done(step_id, "success", "passed ✅")
                return {
                    "final_answer": state["draft_answer"],
                    "review_feedback": "",
                }

            # 开启人工介入时，质检不通过先暂停等人裁决，而不是立刻重写
            if settings.AGENT_HITL_ENABLED:
                decision = interrupt({
                    "type": "review_rejected",
                    "question": state["question"],
                    "draft": state["draft_answer"],
                    "feedback": feedback,
                    "options": ["accept", "rewrite"],
                })
                self._record_step_done(step_id, "success", f"人工裁决: {decision}")
                if decision == "accept":
                    return {
                        "final_answer": state["draft_answer"],
                        "review_feedback": "",
                    }

            new_retry = state.get("retry_count", 0) + 1
            self._record_step_done(
                step_id, "success",
                f"failed review (retry {new_retry}): {feedback[:100]}"
            )
            return {
                "final_answer": "",
                "review_feedback": feedback,
                "retry_count": new_retry,
            }

        # interrupt 抛出的 GraphBubbleUp 是暂停信号，不是节点失败，原样交给图引擎
        except GraphBubbleUp:
            raise

        # 记录节点失败后向上抛出，由上层统一落库为 failed
        except Exception as e:
            self._record_step_failed(run_id, "reviewer", str(e))
            raise

    # ------------------------------------------------------------------
    # 条件路由
    # ------------------------------------------------------------------

    def _route_after_retriever(self, state: AgentState) -> str:
        """Retriever 之后 → 还有子任务就继续检索，否则去 Generator。"""
        if state["current_task_index"] < len(state["sub_tasks"]):
            return "retriever"
        return "generator"

    def _route_after_reviewer(self, state: AgentState) -> str:
        """Reviewer 之后 → 通过就 END，不通过且没超重试就回 Generator。"""
        if state.get("final_answer"):
            return END
        if state.get("retry_count", 0) >= state.get("max_retry", 3):
            return END
        return "generator"

    # ------------------------------------------------------------------
    # 人工介入
    # ------------------------------------------------------------------

    def _pending_interrupts(self, run_id: str) -> list[Any]:
        """从 checkpoint 读取尚未被消费的 interrupt。

        invoke 的返回状态里带 __interrupt__ 键，流式路径拿不到这个键，
        因此统一再查一次 checkpoint，两条路径共用同一套判断。
        """
        snapshot = self._graph.get_state({"configurable": {"thread_id": run_id}})
        return [item for task in snapshot.tasks for item in task.interrupts]

    def _handle_pause(
        self, run_id: str, final_state: dict[str, Any]
    ) -> dict[str, Any] | None:
        """图因人工介入暂停时，落库为等待裁决并返回暂停信息。

        返回 None 表示本轮没有暂停，调用方继续走正常收尾逻辑。
        """
        interrupts = (
            final_state.get("__interrupt__") or self._pending_interrupts(run_id)
        )
        if not interrupts:
            return None

        payload: Any = interrupts[0].value
        self._run_repo.update_status(
            run_id,
            status="awaiting_review",
            checkpoint_id=run_id,
        )
        self._session.commit()
        logger.info("run paused for human review, run_id=%s", run_id)

        return {
            "run_id": run_id,
            "final_answer": "",
            "status": "awaiting_review",
            "error_message": None,
            "interrupt": payload,
        }

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------

    def run(
        self,
        *,
        user_id: int,
        session_id: str,
        question: str,
    ) -> dict[str, Any]:
        """启动一次完整的多 Agent 协作流程。"""
        run_id = str(uuid.uuid4()).replace("-", "")[:16]

        self._run_repo.create(
            user_id=user_id,
            run_id=run_id,
            session_id=session_id,
            question=question,
        )
        self._session.commit()

        config: RunnableConfig = {"configurable": {"thread_id": run_id}}
        initial_state: AgentState = {
            "question": question,
            "user_id": user_id,
            "run_id": run_id,
            "max_retry": 3,
        }

        try:
            final_state = self._graph.invoke(initial_state, config)

            paused = self._handle_pause(run_id, final_state)
            if paused is not None:
                return paused

            answer = final_state.get("final_answer", "")
            if not answer:
                answer = final_state.get("draft_answer", "")

            self._run_repo.update_status(
                run_id,
                status="completed",
                final_answer=answer,
                checkpoint_id=run_id,
                completed=True,
            )
            self._session.commit()

            return {
                "run_id": run_id,
                "final_answer": answer,
                "status": "completed",
                "error_message": None,
            }

        # 兜底捕获：运行失败需要落库为 failed 状态后返回结果，属有意降级
        except Exception as e:  # noqa: BLE001
            self._run_repo.update_status(
                run_id,
                status="failed",
                error_message=str(e)[:1000],
                checkpoint_id=run_id,
                completed=True,
            )
            self._session.commit()

            return {
                "run_id": run_id,
                "final_answer": "",
                "status": "failed",
                "error_message": str(e),
            }

    def resume(self, run_id: str, decision: str | None = None) -> dict[str, Any]:
        """从最近 checkpoint 恢复执行。

        传 decision 表示这是在回答人工介入，会作为 interrupt 的恢复值继续执行。
        """
        run = self._run_repo.get_by_run_id(run_id)
        if not run:
            return {
                "run_id": run_id,
                "final_answer": "",
                "status": "failed",
                "error_message": "run_id 不存在",
            }

        if run.status == "completed":
            return {
                "run_id": run_id,
                "final_answer": run.final_answer or "",
                "status": "completed",
                "error_message": None,
                "interrupt": None,
            }

        # 停在人工介入点时没给裁决值，再跑一遍只会重复暂停，直接把待裁决内容返回
        if run.status == "awaiting_review" and not decision:
            pending = self._pending_interrupts(run_id)
            return {
                "run_id": run_id,
                "final_answer": "",
                "status": "awaiting_review",
                "error_message": None,
                "interrupt": pending[0].value if pending else None,
            }

        config: RunnableConfig = {"configurable": {"thread_id": run_id}}

        try:
            # 有裁决值就走人工恢复，否则按 checkpoint 继续
            resume_payload: Command | None = (
                Command(resume=decision) if decision else None
            )
            final_state = self._graph.invoke(resume_payload, config)

            paused = self._handle_pause(run_id, final_state)
            if paused is not None:
                return paused

            answer = final_state.get("final_answer", "")
            if not answer:
                answer = final_state.get("draft_answer", "")

            self._run_repo.update_status(
                run_id,
                status="completed",
                final_answer=answer,
                checkpoint_id=run_id,
                completed=True,
            )
            self._session.commit()

            return {
                "run_id": run_id,
                "final_answer": answer,
                "status": "completed",
                "error_message": None,
            }

        # 兜底捕获：运行失败需要落库为 failed 状态后返回结果，属有意降级
        except Exception as e:  # noqa: BLE001
            retry_count = (run.retry_count or 0) + 1
            self._run_repo.update_status(
                run_id,
                status="failed",
                error_message=str(e)[:1000],
                checkpoint_id=run_id,
                retry_count=retry_count,
                completed=True,
            )
            self._session.commit()

            return {
                "run_id": run_id,
                "final_answer": "",
                "status": "failed",
                "error_message": str(e),
            }

    # ------------------------------------------------------------------
    # 流式执行（SSE 用）
    # ------------------------------------------------------------------

    def stream_run(
        self,
        *,
        user_id: int,
        session_id: str,
        question: str,
    ) -> Any:
        """启动并流式执行多 Agent 协作流程。

        Yields SSE 事件字典，格式：
          {"type": "node_start", "node": "planner", "run_id": "..."}
          {"type": "node_done", "node": "planner", "run_id": "...", "output_summary": "..."}
          {"type": "final_answer", "run_id": "...", "answer": "..."}
          {"type": "error", "run_id": "...", "message": "..."}
        """
        import json as _json

        run_id = str(uuid.uuid4()).replace("-", "")[:16]

        self._run_repo.create(
            user_id=user_id,
            run_id=run_id,
            session_id=session_id,
            question=question,
        )
        self._session.commit()

        config: RunnableConfig = {"configurable": {"thread_id": run_id}}
        initial_state: AgentState = {
            "question": question,
            "user_id": user_id,
            "run_id": run_id,
            "max_retry": 3,
        }

        def _predict_next(node_name: str, full_state: AgentState) -> str | None:
            """根据刚完成的节点 + 当前完整状态，推测下一个执行的节点名。"""
            if node_name == "planner":
                return "retriever"
            if node_name == "retriever":
                return self._route_after_retriever(full_state)
            if node_name == "generator":
                return "reviewer"
            if node_name == "reviewer":
                routed = self._route_after_reviewer(full_state)
                return routed if routed != END else None
            return None

        yield _json.dumps(
            {"type": "node_start", "node": "planner", "run_id": run_id},
            ensure_ascii=False,
        )

        last_state = initial_state
        try:
            # stream_mode=["updates", "values"] 每次 yield 一个 tuple:
            # ("updates", {刚完成节点的 partial output})
            # ("values",  {完整 state})
            for mode, payload in self._graph.stream(
                initial_state, config, stream_mode=["updates", "values"]
            ):
                if mode == "values":
                    last_state = cast(AgentState, payload)
                    continue

                # mode == "updates": payload = {node_name: {partial output}}
                for node_name, node_output in cast(dict[str, Any], payload).items():
                    # 已完成事件
                    output_summary = ""
                    if node_name == "planner":
                        output_summary = f"拆出 {len(node_output.get('sub_tasks', []))} 个子问题"
                    elif node_name == "retriever":
                        new_docs = len(node_output.get("context_docs", []))
                        output_summary = f"检索到 {new_docs} 个文档"
                    elif node_name == "generator":
                        output_summary = f"生成 {len(node_output.get('draft_answer', ''))} 字"
                    elif node_name == "reviewer":
                        if node_output.get("final_answer"):
                            output_summary = "✅ 通过质检"
                        elif node_output.get("retry_count", 0) >= node_output.get("max_retry", 3):
                            output_summary = "⚠️ 超过最大重试次数"
                        else:
                            output_summary = f"🔁 需重试 ({node_output.get('retry_count', 0)}/3)"

                    yield _json.dumps(
                        {
                            "type": "node_done",
                            "node": node_name,
                            "run_id": run_id,
                            "output_summary": output_summary,
                        },
                        ensure_ascii=False,
                    )

                    # 推测下一个节点并发 node_start
                    next_node = _predict_next(node_name, last_state)
                    if next_node:
                        yield _json.dumps(
                            {
                                "type": "node_start",
                                "node": next_node,
                                "run_id": run_id,
                            },
                            ensure_ascii=False,
                        )

            # 流结束：可能是正常收尾，也可能是质检不通过等待人工裁决
            paused = self._handle_pause(run_id, cast(dict[str, Any], last_state))
            if paused is not None:
                yield _json.dumps(
                    {
                        "type": "interrupt",
                        "run_id": run_id,
                        "interrupt": paused["interrupt"],
                    },
                    ensure_ascii=False,
                )
                yield _json.dumps(
                    {"type": "done", "run_id": run_id},
                    ensure_ascii=False,
                )
                return

            answer = last_state.get("final_answer") or last_state.get("draft_answer", "")

            self._run_repo.update_status(
                run_id,
                status="completed",
                final_answer=answer,
                checkpoint_id=run_id,
                completed=True,
            )
            self._session.commit()

            yield _json.dumps(
                {"type": "final_answer", "run_id": run_id, "answer": answer},
                ensure_ascii=False,
            )
            yield _json.dumps(
                {"type": "done", "run_id": run_id},
                ensure_ascii=False,
            )

        # 兜底捕获：运行失败需要落库为 failed 状态后返回结果，属有意降级
        except Exception as e:  # noqa: BLE001
            self._run_repo.update_status(
                run_id,
                status="failed",
                error_message=str(e)[:1000],
                checkpoint_id=run_id,
                completed=True,
            )
            self._session.commit()

            yield _json.dumps(
                {"type": "error", "run_id": run_id, "message": str(e)},
                ensure_ascii=False,
            )

    def stream_resume(self, run_id: str, decision: str | None = None) -> Any:
        """从 checkpoint 恢复并流式继续执行。

        传 decision 表示这是在回答人工介入，会作为 interrupt 的恢复值继续执行。
        """
        import json as _json

        run = self._run_repo.get_by_run_id(run_id)
        if not run:
            yield _json.dumps(
                {"type": "error", "run_id": run_id, "message": "run_id 不存在"},
                ensure_ascii=False,
            )
            return

        if run.status == "completed":
            yield _json.dumps(
                {
                    "type": "final_answer",
                    "run_id": run_id,
                    "answer": run.final_answer or "",
                },
                ensure_ascii=False,
            )
            return

        config: RunnableConfig = {"configurable": {"thread_id": run_id}}

        # 先发恢复事件（我们不知道具体恢复到哪个节点，让前端从 step 记录推断）
        yield _json.dumps(
            {
                "type": "resumed",
                "run_id": run_id,
                "retry_count": run.retry_count or 0,
            },
            ensure_ascii=False,
        )

        last_state: AgentState | None = None
        # 有裁决值就走人工恢复，否则按 checkpoint 继续
        resume_payload: Command | None = (
            Command(resume=decision) if decision else None
        )
        try:
            for mode, payload in self._graph.stream(
                resume_payload, config, stream_mode=["updates", "values"]
            ):
                if mode == "values":
                    last_state = cast(AgentState, payload)
                    continue

                for node_name, node_output in cast(dict[str, Any], payload).items():
                    output_summary = ""
                    if node_name == "generator":
                        output_summary = (
                            f"生成 {len(node_output.get('draft_answer', ''))} 字"
                        )
                    elif node_name == "reviewer":
                        if node_output.get("final_answer"):
                            output_summary = "✅ 通过质检"
                        else:
                            output_summary = (
                                f"🔁 需重试 ({node_output.get('retry_count', 0)}/3)"
                            )

                    yield _json.dumps(
                        {
                            "type": "node_done",
                            "node": node_name,
                            "run_id": run_id,
                            "output_summary": output_summary,
                        },
                        ensure_ascii=False,
                    )

            # 流结束：可能是正常收尾，也可能再次停在人工介入点
            paused = self._handle_pause(run_id, cast(dict[str, Any], last_state or {}))
            if paused is not None:
                yield _json.dumps(
                    {
                        "type": "interrupt",
                        "run_id": run_id,
                        "interrupt": paused["interrupt"],
                    },
                    ensure_ascii=False,
                )
                yield _json.dumps(
                    {"type": "done", "run_id": run_id},
                    ensure_ascii=False,
                )
                return

            answer = (last_state or {}).get("final_answer") or (last_state or {}).get(
                "draft_answer", ""
            )

            self._run_repo.update_status(
                run_id,
                status="completed",
                final_answer=answer,
                checkpoint_id=run_id,
                completed=True,
            )
            self._session.commit()

            yield _json.dumps(
                {"type": "final_answer", "run_id": run_id, "answer": answer},
                ensure_ascii=False,
            )
            yield _json.dumps(
                {"type": "done", "run_id": run_id},
                ensure_ascii=False,
            )

        # 兜底捕获：运行失败需要落库为 failed 状态后返回结果，属有意降级
        except Exception as e:  # noqa: BLE001
            retry_count = (run.retry_count or 0) + 1
            self._run_repo.update_status(
                run_id,
                status="failed",
                error_message=str(e)[:1000],
                checkpoint_id=run_id,
                retry_count=retry_count,
                completed=True,
            )
            self._session.commit()

            yield _json.dumps(
                {"type": "error", "run_id": run_id, "message": str(e)},
                ensure_ascii=False,
            )

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_run_detail(self, run_id: str) -> dict[str, Any] | None:
        """获取运行详情（含步骤列表）。"""
        run = self._run_repo.get_by_run_id(run_id)
        if not run:
            return None
        steps = self._step_repo.list_by_run(run_id)
        return {"run": run, "steps": steps}
