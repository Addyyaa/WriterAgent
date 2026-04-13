"""add memory fact and mention tables

Revision ID: 9b5b0f4e2c11
Revises: 7f2c2f1a9f61
Create Date: 2026-04-03 10:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType


# revision identifiers, used by Alembic.
revision: str = "9b5b0f4e2c11"
down_revision: Union[str, Sequence[str], None] = "7f2c2f1a9f61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


class PgVector1024(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        return "vector(1024)"


def upgrade() -> None:
    op.create_table(
        "memory_facts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("canonical_text", sa.Text(), nullable=False),
        sa.Column("canonical_hash", sa.Text(), nullable=False),
        sa.Column("embedding", PgVector1024(), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("mention_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "canonical_hash", name="uq_memory_facts_project_hash"),
    )
    op.create_index("idx_memory_facts_project", "memory_facts", ["project_id"], unique=False)
    op.create_index("idx_memory_facts_last_seen", "memory_facts", ["last_seen_at"], unique=False)
    op.create_index(
        "idx_memory_facts_embedding",
        "memory_facts",
        ["embedding"],
        unique=False,
        postgresql_using="ivfflat",
        postgresql_with={"lists": 100},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "memory_mentions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("fact_id", sa.UUID(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=True),
        sa.Column("chunk_type", sa.Text(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("mention_hash", sa.Text(), nullable=False),
        sa.Column("distance_to_fact", sa.Float(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("occurrence_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["fact_id"], ["memory_facts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "fact_id",
            "mention_hash",
            "source_type",
            "source_id",
            "chunk_type",
            name="uq_memory_mentions_dedup",
        ),
    )
    op.create_index("idx_memory_mentions_project", "memory_mentions", ["project_id"], unique=False)
    op.create_index("idx_memory_mentions_fact", "memory_mentions", ["fact_id"], unique=False)
    op.create_index(
        "idx_memory_mentions_source",
        "memory_mentions",
        ["source_type", "source_id"],
        unique=False,
    )
    op.create_index(
        "idx_memory_mentions_last_seen",
        "memory_mentions",
        ["last_seen_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_memory_mentions_last_seen", table_name="memory_mentions")
    op.drop_index("idx_memory_mentions_source", table_name="memory_mentions")
    op.drop_index("idx_memory_mentions_fact", table_name="memory_mentions")
    op.drop_index("idx_memory_mentions_project", table_name="memory_mentions")
    op.drop_table("memory_mentions")

    op.drop_index("idx_memory_facts_embedding", table_name="memory_facts")
    op.drop_index("idx_memory_facts_last_seen", table_name="memory_facts")
    op.drop_index("idx_memory_facts_project", table_name="memory_facts")
    op.drop_table("memory_facts")

