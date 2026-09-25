"""已确认、尚未修复的缺陷，用 xfail(strict=True) 钉住期望行为。

每个用例的 reason 指向 Problem/ 下对应的缺陷文档。用例当前失败是预期结果：
一旦缺陷被修复，strict 模式会让它从 XFAIL 变成 XPASS 并判为失败，
提醒把 xfail 标记删掉、把断言转成正式回归。

之所以不直接删掉这些断言，是因为「没人写下来的期望行为」在代码里等于不存在；
写成 xfail 至少让它在每次 pytest 里被复现一次。
"""
from __future__ import annotations

import inspect
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.api.routes.agent import get_run_detail as get_run_detail_route
from app.api.routes.agent import resume_agent_run
from app.api.routes.documents import delete_document as delete_document_route
from app.core.exceptions import NotFoundError
from app.models import User
from app.repositories.agent_run_repository import AgentRunRepository
from app.repositories.document_repository import DocumentRepository
from app.schemas.agent import AgentRunResumeRequest
from app.schemas.auth import UserOut
from app.services.agent_service import MultiAgentService

# 受害者提问会落进 agent_runs.question，越权读取即可原样拿到
VICTIM_QUESTION = "受害者的私密问题，不应被其他用户读到"


def _identity_of(user: User) -> UserOut:
    """把 ORM 用户转成路由依赖注入时使用的 UserOut。"""

    return UserOut.model_validate(user)


def _seed_victim_run(db: Session, victim: User, status: str) -> str:
    """造一条归属受害者的运行记录，返回 run_id。"""

    run = AgentRunRepository(db).create(
        user_id=victim.id,
        run_id="victim-run-0001",
        session_id="victim-session",
        question=VICTIM_QUESTION,
    )
    run.status = status
    db.commit()
    return run.run_id


@pytest.mark.xfail(
    strict=True,
    reason="GET /agent/runs/{run_id} 未做归属校验；见 Problem/01-agent-run-越权读取.md",
)
def test_run_detail_hides_other_users_run(
    db_session: Session, user: User, other_user: User
) -> None:
    """他人运行详情必须不可见，当前实现会原样返回问题与最终回答。"""

    run_id: str = _seed_victim_run(db_session, user, status="completed")

    response: Any = get_run_detail_route(
        run_id=run_id,
        current_user=_identity_of(other_user),
        db=db_session,
    )

    assert response.data is None


@pytest.mark.xfail(
    strict=True,
    reason="POST /agent/runs/resume 未做归属校验；见 Problem/02-agent-run-越权恢复.md",
)
def test_resume_hides_other_users_run(
    db_session: Session, user: User, other_user: User
) -> None:
    """他人运行不得被他人恢复或读取裁决内容。

    运行停在 awaiting_review 且不带 decision 时，service 只回读待裁决内容、
    不推进图，因此这条用例不触发模型调用，纯粹检验归属校验。
    """

    run_id: str = _seed_victim_run(db_session, user, status="awaiting_review")

    response: Any = resume_agent_run(
        payload=AgentRunResumeRequest(run_id=run_id),
        current_user=_identity_of(other_user),
        db=db_session,
    )

    assert response.data is None


@pytest.mark.xfail(
    strict=True,
    reason="服务层同样缺少归属维度；见 Problem/02-agent-run-越权恢复.md",
)
def test_run_detail_service_layer_accepts_owner_scope() -> None:
    """服务层应能按归属过滤：get_run_detail 的签名需要带 user_id。

    路由层即使想校验也无从下手，必须同时改服务层签名，因此单独钉一条，
    避免只改路由造成「看着修了、其实没修」。
    """

    parameters = inspect.signature(MultiAgentService.get_run_detail).parameters

    assert "user_id" in parameters


def test_documents_route_correctly_rejects_foreign_document(
    db_session: Session, user: User, other_user: User
) -> None:
    """对照用例：documents 路由对他人资源返回 404，是项目里做对了的样子。

    这条用例当前通过，作用是防止其他路由在重构中退化到 agent 路由的写法。
    """

    document = DocumentRepository(db_session).create(
        user_id=user.id, filename="a.txt", file_path="/tmp/a.txt", chunk_count=1
    )
    db_session.commit()

    with pytest.raises(NotFoundError):
        delete_document_route(
            document_id=document.id,
            current_user=_identity_of(other_user),
            db=db_session,
        )
