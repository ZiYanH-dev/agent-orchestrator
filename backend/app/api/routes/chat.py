"""对话 + 会话 API 路由。"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.config.database import get_db
from app.core.response import ApiResponse, success
from app.schemas.auth import UserOut
from app.schemas.chat import ChatHistoryOut, ChatRequest, ChatResponse
from app.schemas.session import SessionCreateIn, SessionOut, SessionRenameIn
from app.services.chat_service import ChatService
from app.services.session_service import SessionService

router = APIRouter(prefix="/chat", tags=["chat"])


# ---------------------------------------------------------------------------
# 会话 CRUD
# ---------------------------------------------------------------------------

@router.get("/sessions", response_model=ApiResponse[list[SessionOut]])
def list_sessions(
    current_user: UserOut = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[list[SessionOut]]:
    """列出当前用户的所有会话。"""
    service: SessionService = SessionService(db)
    sessions: list[SessionOut] = service.list_by_user(current_user.id)
    return success(data=sessions)


@router.post("/sessions", response_model=ApiResponse[SessionOut])
def create_session(
    payload: SessionCreateIn,
    current_user: UserOut = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[SessionOut]:
    """创建新会话。"""
    service: SessionService = SessionService(db)
    session: SessionOut = service.create(user_id=current_user.id, name=payload.name)
    return success(data=session)


@router.put("/sessions/{session_id}", response_model=ApiResponse[SessionOut])
def rename_session(
    session_id: str,
    payload: SessionRenameIn,
    current_user: UserOut = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[SessionOut]:
    """重命名会话。"""
    service: SessionService = SessionService(db)
    session: SessionOut = service.rename(
        session_id=session_id, user_id=current_user.id, name=payload.name
    )
    return success(data=session)


@router.delete("/sessions/{session_id}", response_model=ApiResponse[dict])
def delete_session(
    session_id: str,
    current_user: UserOut = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """删除会话（同时级联删除 ChatRecord）。"""
    service: SessionService = SessionService(db)
    service.delete(session_id=session_id, user_id=current_user.id)
    return success(data={"deleted": True})


# ---------------------------------------------------------------------------
# 对话
# ---------------------------------------------------------------------------

@router.post("", response_model=ApiResponse[ChatResponse])
def chat(
    payload: ChatRequest,
    current_user: UserOut = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[ChatResponse]:
    """执行 RAG 问答（同步）。"""
    service: ChatService = ChatService(db)
    response: ChatResponse = service.chat(
        user_id=current_user.id,
        session_id=payload.session_id,
        question=payload.question,
    )
    return success(data=response)


@router.get("/history", response_model=ApiResponse[ChatHistoryOut])
def chat_history(
    session_id: str = Query(default="default", max_length=64),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: UserOut = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[ChatHistoryOut]:
    """查询当前用户的对话历史。"""
    service: ChatService = ChatService(db)
    history: ChatHistoryOut = service.list_history(
        user_id=current_user.id,
        session_id=session_id,
        skip=skip,
        limit=limit,
    )
    return success(data=history)


@router.post("/stream")
def chat_stream(
    payload: ChatRequest,
    current_user: UserOut = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """流式 RAG 问答（SSE, token 级实时输出）。"""
    service: ChatService = ChatService(db)

    async def event_generator() -> AsyncIterator[str]:
        async for event in service.astream_chat(
            user_id=current_user.id,
            session_id=payload.session_id,
            question=payload.question,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
