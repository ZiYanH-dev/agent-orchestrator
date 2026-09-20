"""安全工具模块：密码哈希与 JWT 令牌编解码。"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config.settings import settings
from app.core.exceptions import AuthenticationError


def hash_password(password: str) -> str:
    """哈希明文密码，返回带盐哈希串。"""

    salt: bytes = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码与哈希串是否匹配。"""

    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def create_access_token(user_id: int) -> str:
    """签发用户访问令牌。"""

    expire_at: datetime = datetime.now(UTC) + timedelta(
        minutes=settings.JWT_EXPIRE_MINUTES
    )
    payload: dict[str, object] = {"sub": str(user_id), "exp": expire_at}
    return jwt.encode(
        payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def decode_access_token(token: str) -> int:
    """解码令牌并返回用户 ID，令牌非法或过期时抛出认证异常。"""

    try:
        payload: dict[str, object] = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.PyJWTError as exc:
        raise AuthenticationError(message="无效的访问令牌") from exc
        
    sub: object = payload.get("sub")
    if not isinstance(sub, (str, int)):
        raise AuthenticationError(message="无效的访问令牌")
    try:
        return int(sub)
    except ValueError as exc:
        raise AuthenticationError(message="无效的访问令牌") from exc
