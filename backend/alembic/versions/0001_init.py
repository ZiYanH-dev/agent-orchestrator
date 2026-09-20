"""初始化迁移：创建 pgvector 扩展 + 4 张核心表。

Revision ID: 0001_init
Revises:
Create Date: 2026-08-29

表结构与 app.models.* 中的 ORM 定义一一对应：
  - users           （用户表）
  - documents       （用户上传文档，外键 → users）
  - chunks          （文档切片，外键 → documents，含 vector 列）
  - chat_records    （对话记录，外键 → users）
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_init"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VECTOR_DIMENSION: int = 768


def upgrade() -> None:
    """全量初始化：扩展 + 4 张表。"""
    # pgvector 扩展（需 superuser；若库已创建过可安全忽略）
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ---- users ----
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("hashed_password", sa.String(length=128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=False)
    op.create_index("ix_users_email", "users", ["email"], unique=False)

    # ---- documents ----
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column(
            "chunk_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_documents_user_id_users"),
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_documents_user_id", "documents", ["user_id"], unique=False)

    # ---- chunks ----
    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(VECTOR_DIMENSION), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_chunks_document_id_documents"),
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"], unique=False)

    # ---- chat_records ----
    op.create_table(
        "chat_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("sources", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_records")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_chat_records_user_id_users"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_chat_records_user_id", "chat_records", ["user_id"], unique=False
    )
    op.create_index(
        "ix_chat_records_session_id", "chat_records", ["session_id"], unique=False
    )


def downgrade() -> None:
    """逆向：删表 → 删扩展。"""
    op.drop_index("ix_chat_records_session_id", table_name="chat_records")
    op.drop_index("ix_chat_records_user_id", table_name="chat_records")
    op.drop_table("chat_records")

    op.drop_index("ix_chunks_document_id", table_name="chunks")
    op.drop_table("chunks")

    op.drop_index("ix_documents_user_id", table_name="documents")
    op.drop_table("documents")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")

    # 注意：有其他 schema 仍在使用 vector 时此语句会失败；属正常现象
    op.execute("DROP EXTENSION IF EXISTS vector")
