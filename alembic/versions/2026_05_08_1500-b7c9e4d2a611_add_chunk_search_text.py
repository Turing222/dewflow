"""add chunk search text

Revision ID: b7c9e4d2a611
Revises: a10ae1555f75
Create Date: 2026-05-08 15:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b7c9e4d2a611"
down_revision: Union[str, Sequence[str], None] = "a10ae1555f75"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "document_chunks",
        sa.Column("search_text", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "document_chunks",
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION document_chunks_search_vector_update()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_vector := to_tsvector(
                'simple',
                COALESCE(NEW.search_text, '')
            );
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_document_chunks_search_vector
        BEFORE INSERT OR UPDATE OF content, search_text
        ON document_chunks
        FOR EACH ROW
        EXECUTE FUNCTION document_chunks_search_vector_update()
        """
    )
    op.execute(
        """
        UPDATE document_chunks
        SET search_text = content
        WHERE search_text = ''
        """
    )
    op.create_index(
        "ix_document_chunks_search_vector",
        "document_chunks",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_document_chunks_search_vector", table_name="document_chunks")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_document_chunks_search_vector ON document_chunks"
    )
    op.execute("DROP FUNCTION IF EXISTS document_chunks_search_vector_update()")
    op.drop_column("document_chunks", "search_vector")
    op.drop_column("document_chunks", "search_text")
