"""Core 层：横切关注点（异常、日志、中间件、统一响应）。"""
from __future__ import annotations

from app.core.exceptions import (
    AlreadyExistsError,
    AppError,
    AuthenticationError,
    NotFoundError,
    ServiceError,
    ValidationError,
)
from app.core.logging import logger
from app.core.middleware import ErrorHandlingMiddleware, RequestLoggingMiddleware
from app.core.response import ApiResponse, error, success
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

__all__ = [
    "AlreadyExistsError",
    "ApiResponse",
    "AppError",
    "AuthenticationError",
    "ErrorHandlingMiddleware",
    "NotFoundError",
    "RequestLoggingMiddleware",
    "ServiceError",
    "ValidationError",
    "create_access_token",
    "decode_access_token",
    "error",
    "hash_password",
    "logger",
    "success",
    "verify_password",
]
