"""Schema 层：Pydantic 数据模型。"""
from __future__ import annotations

from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from app.schemas.chat import (
    ChatHistoryOut,
    ChatRecordOut,
    ChatRequest,
    ChatResponse,
    SourceOut,
)
from app.schemas.document import (
    DocumentCreate,
    DocumentListOut,
    DocumentOut,
)

__all__ = [
    "ChatHistoryOut",
    "ChatRecordOut",
    "ChatRequest",
    "ChatResponse",
    "DocumentCreate",
    "DocumentListOut",
    "DocumentOut",
    "LoginRequest",
    "RegisterRequest",
    "SourceOut",
    "TokenResponse",
    "UserOut",
]
