"""Agent 运行记录 Repository。"""
from __future__ import annotations

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.agent_run import AgentRun
from app.utils.time_utils import utc_now


class AgentRunRepository:
    """Agent 运行记录数据访问层。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        user_id: int,
        run_id: str,
        session_id: str,
        question: str,
    ) -> AgentRun:
        """创建一条新的 Agent 运行记录。"""
        record = AgentRun(
            user_id=user_id,
            run_id=run_id,
            session_id=session_id,
            question=question,
            status="pending",
            started_at=utc_now(),
        )
        self._session.add(record)
        self._session.flush()
        return record

    def get_by_run_id(self, run_id: str) -> AgentRun | None:
        """按 run_id 查询。"""
        return self._session.query(AgentRun).filter(AgentRun.run_id == run_id).first()

    def update_status(
        self,
        run_id: str,
        *,
        status: str,
        final_answer: str | None = None,
        error_message: str | None = None,
        checkpoint_id: str | None = None,
        retry_count: int | None = None,
        completed: bool = False,
    ) -> None:
        """更新运行状态。"""
        run = self.get_by_run_id(run_id)
        if not run:
            return
        run.status = status
        if final_answer is not None:
            run.final_answer = final_answer
        if error_message is not None:
            run.error_message = error_message
        if checkpoint_id is not None:
            run.checkpoint_id = checkpoint_id
        if retry_count is not None:
            run.retry_count = retry_count
        if completed:
            run.completed_at = utc_now()

    def list_by_user(
        self,
        user_id: int,
        *,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[AgentRun]:
        """查询用户的运行记录列表（按 started_at 倒序）。"""
        query = self._session.query(AgentRun).filter(AgentRun.user_id == user_id)
        if session_id:
            query = query.filter(AgentRun.session_id == session_id)
        return query.order_by(desc(AgentRun.started_at)).limit(limit).all()
