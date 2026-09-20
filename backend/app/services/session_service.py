"""会话服务层。

负责会话的创建、查询、重命名与删除。
会话列表走 Redis 缓存，增删改时立即失效，保证缓存与数据库一致。
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.cache import SESSION_LIST_TTL_SECONDS, cache, session_list_key
from app.core.exceptions import NotFoundError
from app.core.logging import logger
from app.repositories.session_repository import SessionRepository
from app.schemas.session import SessionOut


class SessionService:
    """会话服务。"""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo: SessionRepository = SessionRepository(session)

    def list_by_user(self, user_id: int) -> list[SessionOut]:
        """列出当前用户的全部会话，优先命中 Redis 缓存。"""

        key: str = session_list_key(user_id)
        cached = cache.get_json(key)
        if cached is not None:
            logger.info("session list cache hit, user_id=%s count=%d", user_id, len(cached))
            return [SessionOut.model_validate(item) for item in cached]

        sessions = self._repo.list_by_user(user_id)
        result: list[SessionOut] = [SessionOut.model_validate(s) for s in sessions]
        cache.set_json(
            key,
            [item.model_dump(mode="json") for item in result],
            SESSION_LIST_TTL_SECONDS,
        )
        return result

    def create(self, user_id: int, name: str) -> SessionOut:
        """创建新会话。"""

        session_id: str = str(uuid.uuid4())
        obj = self._repo.create(session_id=session_id, user_id=user_id, name=name)
        self._session.commit()
        cache.delete(session_list_key(user_id))
        return SessionOut.model_validate(obj)

    def rename(self, session_id: str, user_id: int, name: str) -> SessionOut:
        """重命名会话，会话不存在时抛出 NotFoundError。"""

        ok: bool = self._repo.rename(session_id=session_id, user_id=user_id, name=name)
        if not ok:
            raise NotFoundError(message="会话不存在")

        self._session.commit()
        cache.delete(session_list_key(user_id))
        updated = self._repo.get(session_id, user_id)
        assert updated is not None
        return SessionOut.model_validate(updated)

    def delete(self, session_id: str, user_id: int) -> None:
        """删除会话，会话不存在时抛出 NotFoundError。"""

        ok: bool = self._repo.delete(session_id=session_id, user_id=user_id)
        if not ok:
            raise NotFoundError(message="会话不存在")

        self._session.commit()
        cache.delete(session_list_key(user_id))
