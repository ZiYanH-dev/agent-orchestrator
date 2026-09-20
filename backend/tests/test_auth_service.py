"""认证服务单元测试。"""
from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401 确保所有模型注册
from app.config.database import Base
from app.core.exceptions import AlreadyExistsError, AuthenticationError
from app.models import User
from app.schemas.auth import TokenResponse, UserOut
from app.services.auth_service import AuthService


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    """构造内存 SQLite 会话，仅建 users 表。"""

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine, tables=[User.__table__])
    session_factory: sessionmaker[Session] = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )
    db: Session = session_factory()
    yield db
    db.close()
    engine.dispose()


def test_register_and_login(session: Session) -> None:
    """注册后可正常登录并返回令牌。"""

    service = AuthService(session)
    user_out: UserOut = service.register(
        username="alice",
        password="secret-123",
        email="alice@example.com",
    )
    assert user_out.id > 0
    assert user_out.username == "alice"
    assert user_out.email == "alice@example.com"

    token: TokenResponse = service.login(username="alice", password="secret-123")
    assert token.access_token != ""


def test_duplicate_username_raises(session: Session) -> None:
    """重复用户名注册抛出已存在异常。"""

    service = AuthService(session)
    service.register(username="alice", password="secret-123")
    with pytest.raises(AlreadyExistsError):
        service.register(username="alice", password="other-456")


def test_wrong_password_raises(session: Session) -> None:
    """错误密码登录抛出认证异常。"""

    service = AuthService(session)
    service.register(username="alice", password="secret-123")
    with pytest.raises(AuthenticationError):
        service.login(username="alice", password="wrong-pass")