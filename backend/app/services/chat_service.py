"""对话服务层。

负责协调 RAG 问答与对话记录持久化。
"""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.orm import Session

from app.models import ChatRecord
from app.repositories.chat_record_repository import ChatRecordRepository
from app.repositories.vector_repository import VectorRepository
from app.schemas.chat import ChatHistoryOut, ChatRecordOut, ChatResponse
from app.services.rag_service import RagService


class ChatService:
    """对话服务。"""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._chat_record_repo: ChatRecordRepository = ChatRecordRepository(session)
        self._rag_service: RagService = RagService(VectorRepository(session))

    def chat(self, user_id: int, session_id: str, question: str) -> ChatResponse:
        """执行 RAG 问答并保存记录。"""

        response: ChatResponse = self._rag_service.chat(
            user_id=user_id,
            session_id=session_id,
            question=question,
        )
        sources_json: str = json.dumps(
            [source.model_dump() for source in response.sources],
            ensure_ascii=False,
        )
        self._chat_record_repo.create(
            user_id=user_id,
            session_id=session_id,
            question=question,
            answer=response.answer,
            sources=sources_json,
        )
        self._session.commit()
        return response

    def list_history(
        self,
        user_id: int,
        session_id: str,
        skip: int,
        limit: int,
    ) -> ChatHistoryOut:
        """分页查询当前用户的对话历史。"""

        result: tuple[list[ChatRecord], int] = self._chat_record_repo.list_by_session(
            user_id=user_id,
            session_id=session_id,
            skip=skip,
            limit=limit,
        )
        records, total = result
        return ChatHistoryOut(
            items=[ChatRecordOut.model_validate(record) for record in records],
            total=total,
        )

    async def astream_chat(
        self, user_id: int, session_id: str, question: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """流式 RAG 问答（同时持久化对话记录）。"""

        full_answer: str = ""
        sources_json: str = "[]"

        async for event in self._rag_service.astream_chat(
            user_id=user_id, session_id=session_id, question=question
        ):
            if event["type"] == "token":
                full_answer += event["data"]
            elif event["type"] == "done":
                sources_json = json.dumps(
                    event["data"].get("sources", []), ensure_ascii=False
                )
            yield event

        # 流式结束后落库
        self._chat_record_repo.create(
            user_id=user_id,
            session_id=session_id,
            question=question,
            answer=full_answer,
            sources=sources_json,
        )
        self._session.commit()
