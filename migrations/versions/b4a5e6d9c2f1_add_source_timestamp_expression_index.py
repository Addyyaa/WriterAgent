"""add source_timestamp expression index for memory chunks

Revision ID: b4a5e6d9c2f1
Revises: 9b5b0f4e2c11
Create Date: 2026-04-05 14:20:00.000000
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b4a5e6d9c2f1"
down_revision: Union[str, Sequence[str], None] = "9b5b0f4e2c11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chunks_source_timestamp
        ON memory_chunks ((metadata_json ->> 'source_timestamp'))
        WHERE metadata_json ? 'source_timestamp'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chunks_source_timestamp")

