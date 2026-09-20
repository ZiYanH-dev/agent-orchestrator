"""0003_sessions — 多会话支持。

Revision ID: 0003_sessions
Revises: 0002_agent_runs
Create Date: 2026-08-31
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_sessions"
down_revision = "0002_agent_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("sessions")
