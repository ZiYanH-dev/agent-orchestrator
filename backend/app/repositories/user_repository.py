"""用户数据访问层。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User


class UserRepository:
    """用户表仓储。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, user_id: int) -> User | None:
        """按 ID 查询用户。"""

        result = self._session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    def get_by_username(self, username: str) -> User | None:
        """按用户名查询用户。"""

        result = self._session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    def get_by_email(self, email: str) -> User | None:
        """按邮箱查询用户。"""

        result = self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    def create(
        self,
        username: str,
        email: str | None,
        hashed_password: str,
    ) -> User:
        """创建用户记录。"""

        user: User = User(
            username=username,
            email=email,
            hashed_password=hashed_password,
        )
        self._session.add(user)
        self._session.flush()
        return user
