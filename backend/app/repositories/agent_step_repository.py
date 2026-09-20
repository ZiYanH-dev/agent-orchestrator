"""Agent 执行步骤 Repository。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.agent_step import AgentStep
from app.utils.time_utils import as_utc, utc_now


class AgentStepRepository:
    """Agent 节点执行日志数据访问层。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        run_id: str,
        node_name: str,
        attempt: int = 1,
        input_summary: str | None = None,
    ) -> AgentStep:
        """创建一条步骤记录（节点开始执行时调用）。"""
        step = AgentStep(
            run_id=run_id,
            node_name=node_name,
            attempt=attempt,
            input_summary=input_summary,
            status="running",
            started_at=utc_now(),
        )
        self._session.add(step)
        self._session.flush()
        return step

    def complete(
        self,
        step_id: int,
        *,
        status: str,
        output_summary: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """标记步骤完成（成功或失败），并计算毫秒级耗时。"""
        step = self._session.query(AgentStep).filter(AgentStep.id == step_id).first()
        if not step:
            return
        now = utc_now()
        step.status = status
        step.output_summary = output_summary
        step.error_message = error_message
        step.completed_at = now
        if step.started_at:
            step.duration_ms = int(
                (now - as_utc(step.started_at)).total_seconds() * 1000
            )

    def list_by_run(self, run_id: str) -> list[AgentStep]:
        """按 run_id 查询所有步骤（按开始时间正序）。"""
        return (
            self._session.query(AgentStep)
            .filter(AgentStep.run_id == run_id)
            .order_by(AgentStep.started_at.asc())
            .all()
        )
