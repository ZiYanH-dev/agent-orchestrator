"""数据库客户端初始化模块。

提供 SQLAlchemy engine、SessionLocal 与 Base 声明基类。
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config.settings import settings


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类。"""


engine = create_engine(
    settings.resolved_database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=settings.DEBUG,
)

SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：获取数据库会话。

    Yields:
        Session: 数据库会话，请求结束后自动关闭。
    """
    
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
