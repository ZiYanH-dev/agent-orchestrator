"""文档处理服务层。

负责文档上传、切分、向量化入库。
"""
from __future__ import annotations

from pathlib import Path

from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy.orm import Session

from app.config.embeddings_client import get_embeddings
from app.config.settings import settings
from app.core.cache import cache, user_retrieval_prefix
from app.core.exceptions import NotFoundError
from app.models import Chunk, Document
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.vector_repository import VectorRepository
from app.schemas.document import DocumentListOut, DocumentOut
from app.utils.file_utils import save_upload_file


class DocumentService:
    """文档处理服务。"""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._document_repo: DocumentRepository = DocumentRepository(session)
        self._chunk_repo: ChunkRepository = ChunkRepository(session)
        self._vector_repo: VectorRepository = VectorRepository(session)

    def ingest_file(
        self,
        user_id: int,
        file_bytes: bytes,
        filename: str,
    ) -> DocumentOut:
        """导入文档：落盘、切分、向量化、入库。

        Args:
            user_id: 所有者用户 ID。
            file_bytes: 上传文件二进制内容。
            filename: 展示文件名。

        Returns:
            DocumentOut: 文档信息。
        """

        file_path: Path = save_upload_file(
            file_bytes=file_bytes,
            original_filename=filename,
        )
        content: str = file_path.read_text(encoding="utf-8")
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
        )
        chunks_text: list[str] = splitter.split_text(content)

        document: Document = self._document_repo.create(
            user_id=user_id,
            filename=filename,
            file_path=str(file_path),
            chunk_count=len(chunks_text),
        )

        embeddings: Embeddings = get_embeddings()
        embedding_matrix: list[list[float]] = embeddings.embed_documents(chunks_text)
        for index in range(len(chunks_text)):
            chunk: Chunk = self._chunk_repo.create(
                document_id=document.id,
                content=chunks_text[index],
                chunk_index=index,
            )
            self._vector_repo.upsert_embedding(chunk.id, embedding_matrix[index])

        self._session.commit()
        self._session.refresh(document)
        cache.delete_prefix(user_retrieval_prefix(user_id))
        
        return DocumentOut.model_validate(document)

    def list_documents(self, user_id: int, skip: int, limit: int) -> DocumentListOut:
        """分页查询当前用户的文档列表。"""

        result: tuple[list[Document], int] = self._document_repo.list_all(
            user_id=user_id,
            skip=skip,
            limit=limit,
        )
        documents, total = result
        return DocumentListOut(
            items=[DocumentOut.model_validate(doc) for doc in documents],
            total=total,
        )

    def delete_document(self, user_id: int, document_id: int) -> None:
        """删除当前用户的文档及其向量，文档不存在时抛出异常。"""

        document: Document | None = self._document_repo.get_by_id(
            user_id=user_id,
            document_id=document_id,
        )
        if document is None:
            raise NotFoundError(message="文档不存在")
        
        self._vector_repo.delete_embedding_by_document(document_id)
        self._chunk_repo.delete_by_document(document_id)
        self._document_repo.delete(document)
        self._session.commit()
        cache.delete_prefix(user_retrieval_prefix(user_id))
