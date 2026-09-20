"""文档相关 Pydantic Schema。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentBase(BaseModel):
    """文档基础字段。"""

    filename: str
    chunk_count: int = 0


class DocumentCreate(DocumentBase):
    """创建文档请求。"""

    file_path: str


class DocumentOut(DocumentBase):
    """文档响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class DocumentListOut(BaseModel):
    """文档列表响应。"""

    items: list[DocumentOut]
    total: int
