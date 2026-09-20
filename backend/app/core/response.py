"""统一响应格式。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一 API 响应包装。"""

    code: int = 0
    message: str = "success"
    data: T | None = None


def success(data: Any = None, message: str = "success") -> ApiResponse[Any]:
    """构造成功响应。"""
    return ApiResponse(code=0, message=message, data=data)


def error(message: str, code: int = 1) -> ApiResponse[None]:
    """构造失败响应。"""
    return ApiResponse(code=code, message=message, data=None)
