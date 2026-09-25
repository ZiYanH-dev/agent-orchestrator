"""测试共享夹具。

数据库统一走内存 SQLite，单元测试因此不依赖 Docker 里的 PostgreSQL。
chunks 表带 pgvector 的 Vector 列，SQLite 方言不认识该类型，所以在模块导入期
注册一条 SQLite 专用编译规则，把它渲染成 TEXT；测试不会写入真实向量，
这条降级只影响 DDL，不影响被测逻辑。

Redis 同样被隔离：autouse 夹具把缓存层的客户端换成内存实现，
测试既不会读写开发环境里的真实 Redis，也不会因 Redis 未启动而失败。
"""
from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401 导入即注册全部 ORM 实体
from app.config.database import Base
from app.core.cache import cache
from app.models import AgentRun, User
from app.utils.time_utils import utc_now
from tests.fakes import FakeRedis


@compiles(Vector, "sqlite")
def _compile_vector_as_text(type_: Any, compiler: Any, **kw: Any) -> str:
    """在 SQLite 上把 pgvector 的 VECTOR 渲染成 TEXT。

    pgvector 只为 PostgreSQL 方言注册了编译实现，SQLite 遇到该类型会直接抛
    UnsupportedCompilationError。测试不需要向量列的真实语义，降级成 TEXT 即可。
    """

    return "TEXT"


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    """把缓存层整体替换为内存实现，保证测试与真实 Redis 隔离。

    要同时改两处，缺一不可：
      - `app.core.cache.redis_client`：RedisCache.__init__ 从这里取客户端，
        测试里新建的 RedisCache 实例才算被隔离；
      - 已构造好的模块级单例 `cache._client`：业务代码 `from app.core.cache
        import cache` 拿到的是这个实例，不换它，服务层仍会打到真实 Redis。
    """

    fake = FakeRedis()
    monkeypatch.setattr("app.core.cache.redis_client", fake)
    monkeypatch.setattr(cache, "_client", fake)
    return fake


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    """内存 SQLite 会话，建好全部 7 张表。

    每个用例拿到独立的库，用例之间不共享数据；会话关闭后引擎立即释放。
    """

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory: sessionmaker[Session] = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    db: Session = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def user(db_session: Session) -> User:
    """一个已入库的普通用户，作为资源的所有者。"""

    obj = User(username="owner", email="owner@example.com", hashed_password="x")
    db_session.add(obj)
    db_session.commit()
    db_session.refresh(obj)
    return obj


@pytest.fixture()
def other_user(db_session: Session) -> User:
    """第二个用户，用于验证按 user_id 的数据隔离。"""

    obj = User(username="intruder", hashed_password="x")
    db_session.add(obj)
    db_session.commit()
    db_session.refresh(obj)
    return obj


@pytest.fixture()
def agent_run(db_session: Session, user: User) -> AgentRun:
    """一条归属 user 的 Agent 运行记录。"""

    record = AgentRun(
        user_id=user.id,
        run_id="run-fixture-0001",
        session_id="default",
        question="夹具问题",
        status="pending",
        started_at=utc_now(),
    )
    db_session.add(record)
    db_session.commit()
    return record
