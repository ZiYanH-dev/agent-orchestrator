"""多 Agent 协作 API 路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.config.database import get_db
from app.core.response import ApiResponse, success
from app.schemas.agent import (
    AgentRunRequest,
    AgentRunResumeRequest,
    AgentRunStartResponse,
)
from app.schemas.auth import UserOut
from app.services.agent_service import MultiAgentService

router = APIRouter(prefix="/agent", tags=["agent"])


# ---------------------------------------------------------------------------
# SSE 流式端点（事件驱动）
# ---------------------------------------------------------------------------

@router.post("/runs/stream")
def start_agent_run_stream(
    payload: AgentRunRequest,
    current_user: UserOut = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """启动多 Agent 协作流程（SSE 流式推送节点状态）。"""

    service = MultiAgentService(db)
    return StreamingResponse(
        (
            f"data: {line}\n\n"
            for line in service.stream_run(
                user_id=current_user.id,
                session_id=payload.session_id,
                question=payload.question,
            )
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/runs/stream/resume")
def resume_agent_run_stream(
    payload: AgentRunResumeRequest,
    current_user: UserOut = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """从 checkpoint 恢复（SSE 流式推送）。"""

    service = MultiAgentService(db)
    return StreamingResponse(
        (
            f"data: {line}\n\n"
            for line in service.stream_resume(payload.run_id)
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/runs", response_model=ApiResponse[AgentRunStartResponse])
def start_agent_run(
    payload: AgentRunRequest,
    current_user: UserOut = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[AgentRunStartResponse]:
    """启动一次多 Agent 协作流程（同步阻塞直到完成/故障）。"""

    service = MultiAgentService(db)
    result = service.run(
        user_id=current_user.id,
        session_id=payload.session_id,
        question=payload.question,
    )
    return success(data=AgentRunStartResponse(
        run_id=result["run_id"],
        status=result["status"],
    ))


@router.post("/runs/resume", response_model=ApiResponse[AgentRunStartResponse])
def resume_agent_run(
    payload: AgentRunResumeRequest,
    current_user: UserOut = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[AgentRunStartResponse]:
    """从 checkpoint 恢复故障的 Agent 运行。"""

    service = MultiAgentService(db)
    result = service.resume(payload.run_id)
    return success(data=AgentRunStartResponse(
        run_id=result["run_id"],
        status=result["status"],
    ))


@router.get("/runs/{run_id}")
def get_run_detail(
    run_id: str,
    current_user: UserOut = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[dict]:
    """获取运行详情（含每个节点的执行日志）。"""

    service = MultiAgentService(db)
    detail = service.get_run_detail(run_id)
    if not detail:
        return success(data=None)

    run = detail["run"]
    steps = detail["steps"]
    return success(data={
        "run": {
            "run_id": run.run_id,
            "session_id": run.session_id,
            "question": run.question,
            "final_answer": run.final_answer,
            "status": run.status,
            "error_message": run.error_message,
            "checkpoint_id": run.checkpoint_id,
            "retry_count": run.retry_count,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        },
        "steps": [
            {
                "node_name": s.node_name,
                "attempt": s.attempt,
                "input_summary": s.input_summary,
                "output_summary": s.output_summary,
                "status": s.status,
                "error_message": s.error_message,
                "duration_ms": s.duration_ms,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
            }
            for s in steps
        ],
    })


@router.get("/runs")
def list_agent_runs(
    session_id: str = Query(default="default", max_length=64),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: UserOut = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """查询当前用户的 Agent 运行记录列表。"""

    from app.repositories.agent_run_repository import AgentRunRepository

    repo = AgentRunRepository(db)
    runs = repo.list_by_user(
        user_id=current_user.id,
        session_id=session_id,
        limit=limit,
    )
    return success(data=[
        {
            "run_id": r.run_id,
            "session_id": r.session_id,
            "question": r.question[:100],
            "status": r.status,
            "retry_count": r.retry_count,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in runs
    ])
