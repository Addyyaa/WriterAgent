"""add summary_text fields for memory compression and recall

Revision ID: d8e9f0a1b2c3
Revises: c4e8f1a2b3c4
Create Date: 2026-04-10 15:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, Sequence[str], None] = "c4e8f1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("memory_chunks", sa.Column("summary_text", sa.Text(), nullable=True))
    op.add_column("memory_facts", sa.Column("summary_text", sa.Text(), nullable=True))

    # 兼容历史数据：先做轻量回填，确保摘要字段可立即参与预算压缩与召回。
    op.execute(
        sa.text(
            "UPDATE memory_chunks SET summary_text = left(coalesce(text, ''), 240) "
            "WHERE summary_text IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE memory_facts SET summary_text = left(coalesce(canonical_text, ''), 240) "
            "WHERE summary_text IS NULL"
        )
    )

    op.create_index(
        "idx_chunks_summary_tsv",
        "memory_chunks",
        [sa.text("to_tsvector('simple', coalesce(summary_text, ''))")],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("idx_chunks_summary_tsv", table_name="memory_chunks")
    op.drop_column("memory_facts", "summary_text")
    op.drop_column("memory_chunks", "summary_text")
