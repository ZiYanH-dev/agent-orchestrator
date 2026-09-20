"""API 层通用依赖。"""
from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.exceptions import AuthenticationError
from app.core.security import decode_access_token
from app.schemas.auth import UserOut
from app.services.auth_service import AuthService

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> UserOut:
    """从请求头解析当前登录用户，失败时抛出认证异常。"""

    if credentials is None:
        raise AuthenticationError(message="未登录或登录已过期")
    user_id: int = decode_access_token(token=credentials.credentials)
    return AuthService(db).get_user_by_id(user_id)
