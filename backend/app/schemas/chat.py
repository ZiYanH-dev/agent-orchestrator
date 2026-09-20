"""对话相关 Pydantic Schema。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    """对话请求。"""

    session_id: str = Field(default="default", max_length=64)
    question: str = Field(min_length=1, max_length=2000)


class SourceOut(BaseModel):
    """检索来源片段。"""

    content: str
    document_id: int
    chunk_index: int
    score: float


class ChatResponse(BaseModel):
    """对话响应。"""

    session_id: str
    question: str
    answer: str
    sources: list[SourceOut]


class ChatRecordOut(BaseModel):
    """对话记录响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: str
    question: str
    answer: str
    sources: str | None = None
    created_at: datetime


class ChatHistoryOut(BaseModel):
    """对话历史响应。"""

    items: list[ChatRecordOut]
    total: int
