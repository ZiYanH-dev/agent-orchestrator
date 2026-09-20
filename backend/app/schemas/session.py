"""会话相关 Schema。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SessionOut(BaseModel):
    id: str
    name: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SessionCreateIn(BaseModel):
    name: str = Field(default="新对话", max_length=128)


class SessionRenameIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
