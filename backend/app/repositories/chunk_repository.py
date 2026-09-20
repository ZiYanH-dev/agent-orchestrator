"""文档分块数据访问层。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk


class ChunkRepository:
    """分块表仓储。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, document_id: int, content: str, chunk_index: int) -> Chunk:
        """创建分块记录。"""

        chunk = Chunk(
            document_id=document_id,
            content=content,
            chunk_index=chunk_index,
        )
        self._session.add(chunk)
        self._session.flush()
        return chunk

    def list_by_document(self, document_id: int) -> list[Chunk]:
        """按文档 ID 查询全部分块。"""

        result = self._session.execute(
            select(Chunk)
            .where(Chunk.document_id == document_id)
            .order_by(Chunk.chunk_index)
        )
        return list(result.scalars().all())

    def delete_by_document(self, document_id: int) -> None:
        """按文档 ID 删除全部分块。"""

        chunks = self.list_by_document(document_id)
        for chunk in chunks:
            self._session.delete(chunk)
