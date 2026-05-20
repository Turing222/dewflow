"""add deleted_at to chat_sessions

Revision ID: d20ae3655f81
Revises: c3f8d6a19b42
Create Date: 2026-05-20 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d20ae3655f81"
down_revision: str | Sequence[str] | None = "c3f8d6a19b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "chat_sessions",
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="软删除时间，NULL 表示未删除",
        ),
    )
    op.create_index(
        op.f("ix_chat_sessions_deleted_at"),
        "chat_sessions",
        ["deleted_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_chat_sessions_deleted_at"), table_name="chat_sessions")
    op.drop_column("chat_sessions", "deleted_at")
