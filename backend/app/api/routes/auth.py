"""认证相关 API 路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.config.database import get_db
from app.core.response import ApiResponse, success
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=ApiResponse[UserOut])
def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
) -> ApiResponse[UserOut]:
    """注册新用户。"""

    service: AuthService = AuthService(db)
    user: UserOut = service.register(
        username=payload.username,
        password=payload.password,
        email=payload.email,
    )
    return success(data=user)


@router.post("/login", response_model=ApiResponse[TokenResponse])
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
) -> ApiResponse[TokenResponse]:
    """用户登录，返回访问令牌。"""

    service: AuthService = AuthService(db)
    tokens: TokenResponse = service.login(
        username=payload.username,
        password=payload.password,
    )
    return success(data=tokens)


@router.get("/me", response_model=ApiResponse[UserOut])
def get_me(
    current_user: UserOut = Depends(get_current_user),
) -> ApiResponse[UserOut]:
    """获取当前登录用户信息。"""

    return success(data=current_user)
