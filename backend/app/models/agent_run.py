"""Agent 运行记录模型。

一次多 Agent 协作流程对应一条 agent_runs 记录，
包含 4 个 Agent（Planner / Retriever / Generator / Reviewer）的完整执行日志。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.config.database import Base


class AgentRun(Base):
    """Agent 运行记录实体。

    一条记录 = 一次完整的多 Agent 协作流程。
    """

    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, unique=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)

    # ---- 最终结果 ----
    final_answer: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- 运行状态 ----
    # pending → planning → retrieving → generating → reviewing → completed / failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- Checkpoint 相关 ----
    checkpoint_id: Mapped[str | None] = mapped_column(String(255), nullable=True,
                                                     comment="最近一次成功 checkpoint 的 thread_id")
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # ---- 耗时 ----
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
