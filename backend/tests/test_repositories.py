"""Repository 层的单元测试。

仓储层是「按 user_id 隔离数据」这条约束的最后一道防线：路由层的鉴权一旦漏掉
某处，仓储层的 where 条件就成了唯一拦截点。因此这里除了 CRUD，重点验证
「限定 user_id 的查询在传入他人 ID 时返回 None / 空」。

数据库用内存 SQLite（见 conftest），不依赖 Docker 里的 PostgreSQL。
VectorRepository 依赖 pgvector 的 `<=>` 运算符，SQLite 无法执行，不在本文件覆盖。
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.models import AgentRun, User
from app.repositories.agent_run_repository import AgentRunRepository
from app.repositories.agent_step_repository import AgentStepRepository
from app.repositories.chat_record_repository import ChatRecordRepository
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.utils.time_utils import utc_now

# ---------------------------------------------------------------------------
# UserRepository
# ---------------------------------------------------------------------------

def test_user_create_and_lookup(db_session: Session) -> None:
    """创建后能按 id / 用户名 / 邮箱三种方式查回。"""

    repo = UserRepository(db_session)
    created: User = repo.create(
        username="alice", email="alice@example.com", hashed_password="hash"
    )
    db_session.commit()

    assert repo.get_by_id(created.id) is created
    assert repo.get_by_username("alice") is created
    assert repo.get_by_email("alice@example.com") is created


def test_user_lookup_misses_return_none(db_session: Session) -> None:
    """查不到时返回 None，不抛异常。"""

    repo = UserRepository(db_session)

    assert repo.get_by_id(999) is None
    assert repo.get_by_username("nobody") is None
    assert repo.get_by_email("nobody@example.com") is None


def test_user_create_flushes_to_get_id(db_session: Session) -> None:
    """create 内部 flush，因此不 commit 也能拿到自增主键。"""

    repo = UserRepository(db_session)
    created: User = repo.create(username="bob", email=None, hashed_password="hash")

    assert created.id is not None and created.id > 0


# ---------------------------------------------------------------------------
# DocumentRepository
# ---------------------------------------------------------------------------

def test_document_get_by_id_is_scoped_to_owner(
    db_session: Session, user: User, other_user: User
) -> None:
    """按 id 查询必须同时匹配 user_id，他人文档返回 None。"""

    repo = DocumentRepository(db_session)
    document = repo.create(
        user_id=user.id, filename="a.txt", file_path="/tmp/a.txt", chunk_count=3
    )
    db_session.commit()

    assert repo.get_by_id(user_id=user.id, document_id=document.id) is document
    assert repo.get_by_id(user_id=other_user.id, document_id=document.id) is None


def test_document_list_all_paginates_and_counts_total(
    db_session: Session, user: User, other_user: User
) -> None:
    """分页返回当页数据与总数；总数只统计当前用户的文档。"""

    repo = DocumentRepository(db_session)
    for index in range(5):
        document = repo.create(
            user_id=user.id,
            filename=f"doc-{index}.txt",
            file_path=f"/tmp/doc-{index}.txt",
            chunk_count=index,
        )
        # created_at 由数据库默认值填充，精度不足以稳定排序，这里显式拉开时间
        document.created_at = utc_now() + timedelta(seconds=index)
    repo.create(
        user_id=other_user.id, filename="x.txt", file_path="/tmp/x.txt", chunk_count=1
    )
    db_session.commit()

    items, total = repo.list_all(user_id=user.id, skip=1, limit=2)

    assert total == 5, "总数不得把他人文档算进来"
    assert len(items) == 2
    assert items[0].filename == "doc-3.txt", "应按 created_at 倒序"
    assert items[1].filename == "doc-2.txt"


def test_document_list_all_returns_empty_for_stranger(
    db_session: Session, user: User, other_user: User
) -> None:
    """没有文档的用户拿到空列表与 0 总数。"""

    DocumentRepository(db_session).create(
        user_id=user.id, filename="a.txt", file_path="/tmp/a.txt", chunk_count=1
    )
    db_session.commit()

    items, total = DocumentRepository(db_session).list_all(
        user_id=other_user.id, skip=0, limit=20
    )

    assert items == []
    assert total == 0


def test_document_delete_removes_row(db_session: Session, user: User) -> None:
    """删除后按 id 查不到。"""

    repo = DocumentRepository(db_session)
    document = repo.create(
        user_id=user.id, filename="a.txt", file_path="/tmp/a.txt", chunk_count=0
    )
    db_session.commit()

    repo.delete(document)
    db_session.commit()

    assert repo.get_by_id(user_id=user.id, document_id=document.id) is None


# ---------------------------------------------------------------------------
# ChunkRepository
# ---------------------------------------------------------------------------

def test_chunk_list_orders_by_chunk_index(db_session: Session, user: User) -> None:
    """分块按 chunk_index 升序返回，与写入顺序无关。"""

    document = DocumentRepository(db_session).create(
        user_id=user.id, filename="a.txt", file_path="/tmp/a.txt", chunk_count=3
    )
    repo = ChunkRepository(db_session)
    repo.create(document_id=document.id, content="第三块", chunk_index=2)
    repo.create(document_id=document.id, content="第一块", chunk_index=0)
    repo.create(document_id=document.id, content="第二块", chunk_index=1)
    db_session.commit()

    chunks = repo.list_by_document(document.id)

    assert [c.chunk_index for c in chunks] == [0, 1, 2]
    assert [c.content for c in chunks] == ["第一块", "第二块", "第三块"]


def test_chunk_list_is_scoped_by_document(db_session: Session, user: User) -> None:
    """只返回属于该文档的分块。"""

    document_repo = DocumentRepository(db_session)
    first = document_repo.create(
        user_id=user.id, filename="a.txt", file_path="/tmp/a.txt", chunk_count=1
    )
    second = document_repo.create(
        user_id=user.id, filename="b.txt", file_path="/tmp/b.txt", chunk_count=1
    )
    repo = ChunkRepository(db_session)
    repo.create(document_id=first.id, content="属于 a", chunk_index=0)
    repo.create(document_id=second.id, content="属于 b", chunk_index=0)
    db_session.commit()

    assert [c.content for c in repo.list_by_document(first.id)] == ["属于 a"]


def test_chunk_delete_by_document_clears_all(db_session: Session, user: User) -> None:
    """按文档删除会清空该文档的全部分块。"""

    document = DocumentRepository(db_session).create(
        user_id=user.id, filename="a.txt", file_path="/tmp/a.txt", chunk_count=2
    )
    repo = ChunkRepository(db_session)
    repo.create(document_id=document.id, content="一", chunk_index=0)
    repo.create(document_id=document.id, content="二", chunk_index=1)
    db_session.commit()

    repo.delete_by_document(document.id)
    db_session.commit()

    assert repo.list_by_document(document.id) == []


# ---------------------------------------------------------------------------
# ChatRecordRepository
# ---------------------------------------------------------------------------

def test_chat_record_list_orders_desc_and_counts(
    db_session: Session, user: User, other_user: User
) -> None:
    """对话历史按创建时间倒序分页，总数不受他人记录影响。"""

    repo = ChatRecordRepository(db_session)
    for index in range(3):
        record = repo.create(
            user_id=user.id,
            session_id="s1",
            question=f"问{index}",
            answer=f"答{index}",
        )
        record.created_at = utc_now() + timedelta(seconds=index)
    repo.create(user_id=user.id, session_id="s2", question="别处", answer="别处")
    repo.create(user_id=other_user.id, session_id="s1", question="他人", answer="他人")
    db_session.commit()

    items, total = repo.list_by_session(user.id, "s1", skip=0, limit=2)

    assert total == 3
    assert [r.question for r in items] == ["问2", "问1"]


def test_chat_record_stores_sources_json(db_session: Session, user: User) -> None:
    """sources 原样保存为字符串，不在这里做解析。"""

    repo = ChatRecordRepository(db_session)
    record = repo.create(
        user_id=user.id,
        session_id="s1",
        question="问",
        answer="答",
        sources='[{"document_id": 1, "score": 0.9}]',
    )
    db_session.commit()

    assert record.sources == '[{"document_id": 1, "score": 0.9}]'


# ---------------------------------------------------------------------------
# SessionRepository
# ---------------------------------------------------------------------------

def test_session_create_and_get_is_scoped(
    db_session: Session, user: User, other_user: User
) -> None:
    """会话按 (id, user_id) 命中，他人拿同一个 id 查不到。"""

    repo = SessionRepository(db_session)
    created = repo.create(session_id="sess-1", user_id=user.id, name="新对话")
    db_session.commit()

    assert repo.get("sess-1", user.id) is created
    assert repo.get("sess-1", other_user.id) is None


def test_session_rename_reports_whether_anything_changed(
    db_session: Session, user: User, other_user: User
) -> None:
    """重命名返回是否命中：自己改得动，别人改不动。"""

    repo = SessionRepository(db_session)
    repo.create(session_id="sess-1", user_id=user.id, name="旧名")
    db_session.commit()

    assert repo.rename("sess-1", other_user.id, "被篡改") is False
    assert repo.rename("sess-1", user.id, "新名") is True
    db_session.commit()

    updated = repo.get("sess-1", user.id)
    assert updated is not None
    assert updated.name == "新名"


def test_session_delete_reports_whether_row_existed(
    db_session: Session, user: User, other_user: User
) -> None:
    """删除他人会话返回 False 且数据仍在；删自己的返回 True。"""

    repo = SessionRepository(db_session)
    repo.create(session_id="sess-1", user_id=user.id, name="对话")
    db_session.commit()

    assert repo.delete("sess-1", other_user.id) is False
    assert repo.get("sess-1", user.id) is not None

    assert repo.delete("sess-1", user.id) is True
    assert repo.get("sess-1", user.id) is None


def test_session_list_is_ordered_by_updated_at_desc(
    db_session: Session, user: User, other_user: User
) -> None:
    """会话列表按 updated_at 倒序，且只含当前用户。"""

    repo = SessionRepository(db_session)
    for index in range(3):
        created = repo.create(
            session_id=f"sess-{index}", user_id=user.id, name=f"对话{index}"
        )
        created.updated_at = utc_now() + timedelta(seconds=index)
    repo.create(session_id="other", user_id=other_user.id, name="他人对话")
    db_session.commit()

    sessions = repo.list_by_user(user.id)

    assert [s.id for s in sessions] == ["sess-2", "sess-1", "sess-0"]


# ---------------------------------------------------------------------------
# AgentRunRepository
# ---------------------------------------------------------------------------

def test_agent_run_create_initialises_pending(db_session: Session, user: User) -> None:
    """新建运行记录初始状态为 pending，并写入开始时间。"""

    repo = AgentRunRepository(db_session)
    run = repo.create(
        user_id=user.id, run_id="run-1", session_id="s1", question="问题"
    )
    db_session.commit()

    assert run.status == "pending"
    assert run.started_at is not None
    assert run.completed_at is None
    assert run.retry_count == 0
    assert repo.get_by_run_id("run-1") is run


def test_agent_run_get_by_run_id_miss(db_session: Session) -> None:
    """查不到的 run_id 返回 None。"""

    assert AgentRunRepository(db_session).get_by_run_id("nope") is None


def test_agent_run_update_status_leaves_omitted_fields_untouched(
    db_session: Session, user: User
) -> None:
    """只更新传入的字段：final_answer 传 None 时不得把已有答案擦掉。"""

    repo = AgentRunRepository(db_session)
    repo.create(user_id=user.id, run_id="run-1", session_id="s1", question="问题")
    repo.update_status("run-1", status="completed", final_answer="答案", completed=True)
    db_session.commit()

    repo.update_status("run-1", status="failed", error_message="出错了")
    db_session.commit()

    run = repo.get_by_run_id("run-1")
    assert run is not None
    assert run.status == "failed"
    assert run.error_message == "出错了"
    assert run.final_answer == "答案", "未传 final_answer 时必须保留原值"
    assert run.checkpoint_id is None


def test_agent_run_update_status_sets_completed_at_once(
    db_session: Session, user: User
) -> None:
    """completed=True 才写完成时间；之后不带 completed 的更新不会改动它。"""

    repo = AgentRunRepository(db_session)
    repo.create(user_id=user.id, run_id="run-1", session_id="s1", question="问题")
    repo.update_status("run-1", status="completed", final_answer="答案", completed=True)
    db_session.commit()
    first_completed_at = repo.get_by_run_id("run-1")

    assert first_completed_at is not None
    stamp = first_completed_at.completed_at
    assert stamp is not None

    repo.update_status("run-1", status="running")
    db_session.commit()

    again = repo.get_by_run_id("run-1")
    assert again is not None
    assert again.completed_at == stamp


def test_agent_run_update_status_on_unknown_run_is_noop(db_session: Session) -> None:
    """更新不存在的 run_id 静默跳过，不抛异常。"""

    AgentRunRepository(db_session).update_status("ghost", status="completed")


def test_agent_run_list_filters_by_user_and_session(
    db_session: Session, user: User, other_user: User
) -> None:
    """列表按用户与会话过滤，并受 limit 约束。"""

    repo = AgentRunRepository(db_session)
    for index in range(4):
        run = repo.create(
            user_id=user.id,
            run_id=f"run-{index}",
            session_id="target" if index < 3 else "elsewhere",
            question=f"问题{index}",
        )
        run.started_at = utc_now() + timedelta(seconds=index)
    repo.create(user_id=other_user.id, run_id="run-x", session_id="target", question="他人")
    db_session.commit()

    scoped = repo.list_by_user(user.id, session_id="target", limit=10)
    assert [r.run_id for r in scoped] == ["run-2", "run-1", "run-0"]

    limited = repo.list_by_user(user.id, session_id="target", limit=2)
    assert [r.run_id for r in limited] == ["run-2", "run-1"]

    all_sessions = repo.list_by_user(user.id, limit=10)
    assert len(all_sessions) == 4


# ---------------------------------------------------------------------------
# AgentStepRepository
# ---------------------------------------------------------------------------

def test_agent_step_create_sets_running_state(
    db_session: Session, user: User, agent_run: AgentRun
) -> None:
    """新建步骤状态为 running，并记录尝试序号。"""

    repo = AgentStepRepository(db_session)
    step = repo.create(
        run_id=agent_run.run_id, node_name="planner", attempt=1, input_summary="输入"
    )
    db_session.commit()

    assert step.status == "running"
    assert step.attempt == 1
    assert step.started_at is not None
    assert step.completed_at is None
    assert step.duration_ms is None


def test_agent_step_complete_records_duration(
    db_session: Session, user: User, agent_run: AgentRun
) -> None:
    """完成时写入状态、摘要与毫秒级耗时。"""

    repo = AgentStepRepository(db_session)
    step = repo.create(run_id=agent_run.run_id, node_name="planner")
    db_session.commit()

    repo.complete(step.id, status="success", output_summary="拆出 2 个子问题")
    db_session.commit()

    assert step.status == "success"
    assert step.output_summary == "拆出 2 个子问题"
    assert step.completed_at is not None
    assert step.duration_ms is not None
    assert step.duration_ms >= 0


def test_agent_step_complete_records_failure(
    db_session: Session, user: User, agent_run: AgentRun
) -> None:
    """失败时记录错误信息。"""

    repo = AgentStepRepository(db_session)
    step = repo.create(run_id=agent_run.run_id, node_name="retriever")
    db_session.commit()

    repo.complete(step.id, status="failed", error_message="KeyError: 'context_docs'")
    db_session.commit()

    assert step.status == "failed"
    assert step.error_message == "KeyError: 'context_docs'"


def test_agent_step_complete_on_unknown_id_is_noop(db_session: Session) -> None:
    """标记不存在的步骤静默跳过。"""

    AgentStepRepository(db_session).complete(9999, status="success")


def test_agent_step_list_orders_by_started_at(
    db_session: Session, user: User, agent_run: AgentRun
) -> None:
    """步骤列表按开始时间正序，多次重放时按 attempt 递增排列。"""

    repo = AgentStepRepository(db_session)
    base = utc_now()
    for index, node in enumerate(["planner", "retriever", "generator"]):
        step = repo.create(run_id=agent_run.run_id, node_name=node)
        step.started_at = base + timedelta(seconds=index)
    db_session.commit()

    steps = repo.list_by_run(agent_run.run_id)

    assert [s.node_name for s in steps] == ["planner", "retriever", "generator"]


def test_agent_step_list_is_scoped_by_run(
    db_session: Session, user: User, agent_run: AgentRun
) -> None:
    """只返回属于该 run 的步骤。"""

    other = AgentRunRepository(db_session).create(
        user_id=user.id, run_id="run-2", session_id="s1", question="另一个问题"
    )
    repo = AgentStepRepository(db_session)
    repo.create(run_id=agent_run.run_id, node_name="planner")
    repo.create(run_id=other.run_id, node_name="reviewer")
    db_session.commit()

    assert [s.node_name for s in repo.list_by_run(agent_run.run_id)] == ["planner"]
