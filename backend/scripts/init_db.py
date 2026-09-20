"""数据库初始化脚本。

创建 pgvector 扩展与所有数据表。
"""
from __future__ import annotations

from sqlalchemy import text

import app.models  # noqa: F401  确保模型注册
from app.config.database import Base, engine


def init_db() -> None:
    """初始化数据库。"""
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)
    print("数据库初始化完成")


if __name__ == "__main__":
    init_db()