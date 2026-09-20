"""Repository 层：数据访问。"""
from __future__ import annotations

from app.repositories.chat_record_repository import ChatRecordRepository
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.user_repository import UserRepository
from app.repositories.vector_repository import VectorRepository

__all__ = [
    "ChatRecordRepository",
    "ChunkRepository",
    "DocumentRepository",
    "UserRepository",
    "VectorRepository",
]
