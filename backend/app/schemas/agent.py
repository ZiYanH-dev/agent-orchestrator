"""Agent 相关 Pydantic Schema。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ---- 请求 ----

class AgentRunRequest(BaseModel):
    """Agent 运行请求。"""

    session_id: str = Field(default="default", max_length=64)
    question: str = Field(min_length=1, max_length=2000)


class AgentRunResumeRequest(BaseModel):
    """恢复运行请求。"""

    run_id: str = Field(description="之前故障的 run_id")


# ---- 响应 ----

class AgentRunStepOut(BaseModel):
    """单个步骤的执行日志。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    node_name: str
    attempt: int
    input_summary: str | None = None
    output_summary: str | None = None
    status: str  # running / success / failed
    error_message: str | None = None
    duration_ms: int | None = None
    started_at: datetime
    completed_at: datetime | None = None


class AgentRunOut(BaseModel):
    """Agent 运行记录响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: str
    session_id: str
    question: str
    final_answer: str | None = None
    status: str  # pending / planning / retrieving / generating / reviewing / completed / failed
    error_message: str | None = None
    checkpoint_id: str | None = None
    retry_count: int
    started_at: datetime
    completed_at: datetime | None = None


class AgentRunDetailOut(AgentRunOut):
    """带步骤列表的运行详情。"""

    steps: list[AgentRunStepOut] = Field(default_factory=list)


class AgentRunStartResponse(BaseModel):
    """启动运行的响应（返回 run_id，前端用来轮询/连接 SSE）。"""

    run_id: str
    status: str


# ---- SSE 事件类型 ----

class AgentSSEEvent(BaseModel):
    """SSE 事件格式。"""

    event: str  # step_start / step_end / run_complete / run_failed
    data: dict
