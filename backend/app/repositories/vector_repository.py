"""向量检索数据访问层（pgvector）。"""
from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.config.settings import settings


class VectorRepository:
    """基于 pgvector 的向量检索仓储。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def search(
        self,
        user_id: int,
        query_vector: list[float],
        top_k: int,
    ) -> list[tuple[int, int, int, str, float]]:
        """执行向量相似度检索（限定当前用户文档）。

        Args:
            user_id: 用户 ID。
            query_vector: 查询向量。
            top_k: 返回条数。

        Returns:
            list[tuple[int, int, int, str, float]]:
            (chunk_id, document_id, chunk_index, content, score) 列表。
        """

        sql = text(
            """
            SELECT c.id, c.document_id, c.chunk_index, c.content,
                   1 - (c.embedding <=> :query_vector) AS score
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.user_id = :user_id
            ORDER BY c.embedding <=> :query_vector
            LIMIT :top_k
            """
        ).bindparams(
            bindparam(
                "query_vector",
                value=query_vector,
                type_=Vector(settings.VECTOR_DIMENSION),
            ),
            bindparam("user_id", value=user_id),
            bindparam("top_k", value=top_k),
        )
        result = self._session.execute(sql)
        rows = result.fetchall()
        return [(int(r[0]), int(r[1]), int(r[2]), str(r[3]), float(r[4])) for r in rows]

    def upsert_embedding(self, chunk_id: int, embedding: list[float]) -> None:
        """写入分块向量。"""

        sql = text(
            "UPDATE chunks SET embedding = :embedding WHERE id = :chunk_id"
        ).bindparams(
            bindparam(
                "embedding",
                value=embedding,
                type_=Vector(settings.VECTOR_DIMENSION),
            ),
            bindparam("chunk_id", value=chunk_id),
        )
        self._session.execute(sql)

    def delete_embedding_by_document(self, document_id: int) -> None:
        """按文档 ID 清空向量。"""

        sql = text(
            "UPDATE chunks SET embedding = NULL WHERE document_id = :doc_id"
        ).bindparams(bindparam("doc_id", value=document_id))
        self._session.execute(sql)
