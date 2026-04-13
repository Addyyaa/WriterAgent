"""add memory_chunks fts expression index

Revision ID: d3c6f9a1b2e4
Revises: b4a5e6d9c2f1
Create Date: 2026-04-05 15:40:00.000000
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d3c6f9a1b2e4"
down_revision: Union[str, Sequence[str], None] = "b4a5e6d9c2f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chunks_text_tsv
        ON memory_chunks
        USING gin (to_tsvector('simple', coalesce(text, '')))
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chunks_text_tsv")

