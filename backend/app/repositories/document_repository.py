"""文档数据访问层。"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Document


class DocumentRepository:
    """文档表仓储。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        user_id: int,
        filename: str,
        file_path: str,
        chunk_count: int,
    ) -> Document:
        """创建文档记录。"""

        document: Document = Document(
            user_id=user_id,
            filename=filename,
            file_path=file_path,
            chunk_count=chunk_count,
        )
        self._session.add(document)
        self._session.flush()
        return document

    def get_by_id(self, user_id: int, document_id: int) -> Document | None:
        """按 ID 查询文档（限定当前用户）。"""

        result = self._session.execute(
            select(Document).where(
                Document.id == document_id,
                Document.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    def list_all(
        self,
        user_id: int,
        skip: int,
        limit: int,
    ) -> tuple[list[Document], int]:
        """分页查询当前用户的文档列表。"""

        total_result = self._session.execute(
            select(func.count(Document.id)).where(Document.user_id == user_id)
        )
        total: int = total_result.scalar_one()
        result = self._session.execute(
            select(Document)
            .where(Document.user_id == user_id)
            .order_by(Document.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    def delete(self, document: Document) -> None:
        """删除文档记录。"""

        self._session.delete(document)
