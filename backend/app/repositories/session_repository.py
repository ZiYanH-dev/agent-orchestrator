"""会话 Repository。"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session as OrmSession

from app.models.session import Session
from app.utils.time_utils import utc_now


class SessionRepository:
    """会话数据访问层。"""

    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def list_by_user(self, user_id: int) -> Sequence[Session]:
        stmt = (
            select(Session)
            .where(Session.user_id == user_id)
            .order_by(Session.updated_at.desc())
        )
        return self._session.scalars(stmt).all()

    def get(self, session_id: str, user_id: int) -> Session | None:
        stmt = select(Session).where(
            Session.id == session_id, Session.user_id == user_id
        )
        return self._session.scalar(stmt)

    def create(self, session_id: str, user_id: int, name: str) -> Session:
        obj = Session(id=session_id, user_id=user_id, name=name)
        self._session.add(obj)
        self._session.flush()
        return obj

    def rename(self, session_id: str, user_id: int, name: str) -> bool:
        stmt = (
            update(Session)
            .where(Session.id == session_id, Session.user_id == user_id)
            .values(name=name, updated_at=utc_now())
        )
        result = cast(CursorResult[Any], self._session.execute(stmt))
        return result.rowcount > 0

    def delete(self, session_id: str, user_id: int) -> bool:
        obj = self.get(session_id, user_id)
        if obj is None:
            return False
        self._session.delete(obj)
        self._session.flush()
        return True
