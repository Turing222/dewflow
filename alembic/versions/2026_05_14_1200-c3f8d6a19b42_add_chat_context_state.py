"""Add chat context state.

Revision ID: c3f8d6a19b42
Revises: b7c9e4d2a611
Create Date: 2026-05-14 12:00:00.000000
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c3f8d6a19b42"
down_revision: Union[str, Sequence[str], None] = "b7c9e4d2a611"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column(
            "context_state",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "chat_sessions",
        sa.Column(
            "context_state_version",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_sessions", "context_state_version")
    op.drop_column("chat_sessions", "context_state")
