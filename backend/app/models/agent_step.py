"""Agent 执行步骤模型。

一条 agent_steps 记录 = 一个 Agent 节点（Planner / Retriever / Generator / Reviewer）
的一次执行。一次 AgentRun 可以有多个 step（正常执行 + 故障恢复后的重试）。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.config.database import Base


class AgentStep(Base):
    """Agent 节点执行日志实体。"""

    __tablename__ = "agent_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_runs.run_id", ondelete="CASCADE"),
        index=True, nullable=False
    )

    # ---- 节点信息 ----
    # planner / retriever / generator / reviewer
    node_name: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # 第几次执行（从 1 开始，恢复后重试会递增）
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # ---- 输入/输出摘要 ----
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- 执行结果 ----
    # running / success / failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- 耗时（毫秒） ----
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
