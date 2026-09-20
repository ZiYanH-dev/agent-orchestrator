"""认证服务层。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.exceptions import AlreadyExistsError, AuthenticationError
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import TokenResponse, UserOut


class AuthService:
    """认证服务：注册、登录、当前用户查询。"""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._user_repo: UserRepository = UserRepository(session)

    def register(
        self,
        username: str,
        password: str,
        email: str | None = None,
    ) -> UserOut:
        """注册新用户，用户名或邮箱冲突时抛出已存在异常。"""

        if self._user_repo.get_by_username(username) is not None:
            raise AlreadyExistsError(message="用户名已存在")
        if email is not None and self._user_repo.get_by_email(email) is not None:
            raise AlreadyExistsError(message="邮箱已被注册")
        hashed_password: str = hash_password(password)
        user: User = self._user_repo.create(
            username=username,
            email=email,
            hashed_password=hashed_password,
        )
        self._session.commit()
        return UserOut.model_validate(user)

    def login(self, username: str, password: str) -> TokenResponse:
        """校验用户名密码，失败时抛出认证异常。"""

        user: User | None = self._user_repo.get_by_username(username)
        if user is None or not verify_password(password, user.hashed_password):
            raise AuthenticationError(message="用户名或密码错误")
        if not user.is_active:
            raise AuthenticationError(message="账号已被禁用")
        access_token: str = create_access_token(user_id=user.id)
        return TokenResponse(access_token=access_token)

    def get_user_by_id(self, user_id: int) -> UserOut:
        """按 ID 查询用户，不存在或已禁用时抛出认证异常。"""

        user: User | None = self._user_repo.get_by_id(user_id)
        if user is None or not user.is_active:
            raise AuthenticationError(message="用户不存在或已被禁用")
        return UserOut.model_validate(user)
