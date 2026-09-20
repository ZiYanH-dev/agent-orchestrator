"""文档相关 API 路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.config.database import get_db
from app.core.response import ApiResponse, success
from app.schemas.auth import UserOut
from app.schemas.document import DocumentListOut, DocumentOut
from app.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=ApiResponse[DocumentOut])
def upload_document(
    file: UploadFile = File(...),
    current_user: UserOut = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[DocumentOut]:
    """上传并导入文档。"""

    service: DocumentService = DocumentService(db)
    document: DocumentOut = service.ingest_file(
        user_id=current_user.id,
        file_bytes=file.file.read(),
        filename=file.filename or "unnamed.txt",
    )
    return success(data=document)


@router.get("", response_model=ApiResponse[DocumentListOut])
def list_documents(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: UserOut = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[DocumentListOut]:
    """分页查询当前用户的文档列表。"""

    service: DocumentService = DocumentService(db)
    result: DocumentListOut = service.list_documents(
        user_id=current_user.id,
        skip=skip,
        limit=limit,
    )
    return success(data=result)


@router.delete("/{document_id}", response_model=ApiResponse[None])
def delete_document(
    document_id: int,
    current_user: UserOut = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[None]:
    """删除当前用户的文档及其向量。"""

    service: DocumentService = DocumentService(db)
    service.delete_document(user_id=current_user.id, document_id=document_id)
    return success(data=None)
