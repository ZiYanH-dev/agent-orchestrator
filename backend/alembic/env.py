"""Alembic 环境配置。

- 通过 pydantic-settings 读取 .env 中的 DATABASE_URL
- 注册所有 SQLAlchemy 模型的 metadata（import app.models 即可）
- 处理 pgvector 自定义类型，避免自动生成迁移时误报
- 设置统一的约束命名约定，避免 SQLite/PostgreSQL 下约束名不一致
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

# 注册所有 ORM 模型（metadata 需要被导入才能收集表信息）
import app.models  # noqa: F401  让模型注册到 Base.metadata
from alembic import context
from app.config.database import Base
from app.config.settings import settings

# Alembic Config 对象，获取 alembic.ini 中的值
config = context.config

# 使用 .env 中的连接串覆盖 alembic.ini 的占位
config.set_main_option("sqlalchemy.url", settings.resolved_database_url)

# 设置 Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 给 autogenerate 提供目标 metadata
target_metadata = Base.metadata

# 统一约束命名约定（数据库升级/降级时可预测的约束名，便于回滚）
naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
target_metadata.naming_convention = naming_convention


def run_migrations_offline() -> None:
    """离线模式运行迁移（不建立 DB 连接，直接生成 SQL 文本）。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式运行迁移（建立真实 DB 连接）。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
