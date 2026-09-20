"""RAG 问答服务层。

负责构建 LangGraph 检索增强生成链路，并执行问答。
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.documents import Document as LCDocument
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.config.embeddings_client import get_embeddings
from app.config.llm_client import get_llm
from app.config.settings import settings
from app.core.cache import RETRIEVAL_TTL_SECONDS, cache, retrieval_key
from app.core.logging import logger
from app.repositories.vector_repository import VectorRepository
from app.schemas.chat import ChatResponse, SourceOut


class RagState(TypedDict):
    """LangGraph 状态。"""

    question: str
    user_id: int
    context: list[LCDocument]
    answer: str


class RagService:
    """RAG 问答服务。"""

    def __init__(self, vector_repository: VectorRepository) -> None:
        self._vector_repository = vector_repository
        self._graph: Any = self._build_graph()

    def _retrieve(self, state: RagState) -> RagState:
        """检索阶段：向量检索当前用户的相关文档片段，命中缓存则跳过向量化与查询。"""

        user_id: int = state["user_id"]
        question: str = state["question"]
        cache_key: str = retrieval_key(user_id, question)
        cached_rows = cache.get_json(cache_key)

        if cached_rows is not None:
            logger.info("retrieval cache hit, user_id=%s", user_id)
            rows = [tuple(row) for row in cached_rows]
        else:
            embeddings: Embeddings = get_embeddings()
            query_vector: list[float] = embeddings.embed_query(question)
            rows = self._vector_repository.search(
                user_id=user_id,
                query_vector=query_vector,
                top_k=settings.RETRIEVE_TOP_K,
            )
            cache.set_json(cache_key, [list(row) for row in rows], RETRIEVAL_TTL_SECONDS)

        docs: list[LCDocument] = [
            LCDocument(
                page_content=row[3],
                metadata={
                    "document_id": row[1],
                    "chunk_id": row[0],
                    "chunk_index": row[2],
                    "score": row[4],
                },
            )
            for row in rows
        ]
        return {**state, "context": docs}

    def _generate(self, state: RagState) -> RagState:
        """生成阶段：基于上下文生成回答。"""

        context_text: str = "\n\n".join(doc.page_content for doc in state["context"])
        prompt = ChatPromptTemplate.from_template(
            """基于以下上下文内容回答问题。如果无法从上下文中找到答案，请直接回复"未找到相关信息"。

上下文内容：
{context}

问题：{question}

回答："""
        )
        llm: BaseChatModel = get_llm()
        chain = prompt | llm | StrOutputParser()
        answer: str = chain.invoke(
            {"context": context_text, "question": state["question"]}
        )
        return {**state, "answer": answer}

    def _build_graph(self) -> Any:
        """构建 LangGraph 状态图。"""

        graph = StateGraph(RagState)
        graph.add_node("retrieve", self._retrieve)
        graph.add_node("generate", self._generate)
        graph.add_edge(START, "retrieve")
        graph.add_edge("retrieve", "generate")
        graph.add_edge("generate", END)
        return graph.compile()

    def chat(self, user_id: int, session_id: str, question: str) -> ChatResponse:
        """执行一次 RAG 问答。

        Args:
            user_id: 所有者用户 ID。
            session_id: 会话 ID。
            question: 用户问题。

        Returns:
            ChatResponse: 回答与来源。
        """

        result: dict[str, Any] = self._graph.invoke(
            {"question": question, "user_id": user_id}
        )
        sources: list[SourceOut] = [
            SourceOut(
                content=doc.page_content,
                document_id=int(doc.metadata["document_id"]),
                chunk_index=int(doc.metadata.get("chunk_index", 0)),
                score=float(doc.metadata.get("score", 0.0)),
            )
            for doc in result.get("context", [])
        ]
        return ChatResponse(
            session_id=session_id,
            question=question,
            answer=result.get("answer", ""),
            sources=sources,
        )

    async def astream_chat(
        self, user_id: int, session_id: str, question: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """流式 RAG 问答（token 级流式输出）。

        SSE 事件类型：
          - sources: 检索完成，返回来源列表
          - token: LLM 生成的一个 token
          - done: 生成完成，返回完整 answer + sources
        """

        # 1) 检索（同步，向量检索很快）
        result: dict[str, Any] = await self._graph.ainvoke(
            {"question": question, "user_id": user_id}
        )
        sources: list[SourceOut] = [
            SourceOut(
                content=doc.page_content,
                document_id=int(doc.metadata["document_id"]),
                chunk_index=int(doc.metadata.get("chunk_index", 0)),
                score=float(doc.metadata.get("score", 0.0)),
            )
            for doc in result.get("context", [])
        ]
        yield {"type": "sources", "data": [s.model_dump() for s in sources]}

        # 2) 流式生成（token 级）
        context_text: str = "\n\n".join(doc.page_content for doc in result.get("context", []))
        prompt = ChatPromptTemplate.from_template(
            """基于以下上下文内容回答问题。如果无法从上下文中找到答案，请直接回复"未找到相关信息"。

上下文内容：
{context}

问题：{question}

回答："""
        )
        llm: BaseChatModel = get_llm()
        chain = prompt | llm | StrOutputParser()

        full_answer: str = ""
        async for chunk in chain.astream(
            {"context": context_text, "question": question}
        ):
            full_answer += chunk
            yield {"type": "token", "data": chunk}

        yield {
            "type": "done",
            "data": {
                "session_id": session_id,
                "question": question,
                "answer": full_answer,
                "sources": [s.model_dump() for s in sources],
            },
        }
