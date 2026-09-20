"""对话记录数据访问层。"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ChatRecord


class ChatRecordRepository:
    """对话记录表仓储。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        user_id: int,
        session_id: str,
        question: str,
        answer: str,
        sources: str | None = None,
    ) -> ChatRecord:
        """创建对话记录。"""

        record: ChatRecord = ChatRecord(
            user_id=user_id,
            session_id=session_id,
            question=question,
            answer=answer,
            sources=sources,
        )
        self._session.add(record)
        self._session.flush()
        return record

    def list_by_session(
        self,
        user_id: int,
        session_id: str,
        skip: int,
        limit: int,
    ) -> tuple[list[ChatRecord], int]:
        """按会话 ID 分页查询当前用户的对话记录。"""

        total_result = self._session.execute(
            select(func.count(ChatRecord.id)).where(
                ChatRecord.user_id == user_id,
                ChatRecord.session_id == session_id,
            )
        )
        total: int = total_result.scalar_one()
        result = self._session.execute(
            select(ChatRecord)
            .where(
                ChatRecord.user_id == user_id,
                ChatRecord.session_id == session_id,
            )
            .order_by(ChatRecord.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all()), total
