"""add retrieval eval and lifecycle persistence tables

Revision ID: f2c3d4e5f6a7
Revises: e8f1b2c3d4a5
Create Date: 2026-04-07 08:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "e8f1b2c3d4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "retrieval_eval_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("variant", sa.Text(), nullable=False),
        sa.Column("rerank_backend", sa.Text(), nullable=True),
        sa.Column(
            "impressed_doc_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("clicked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("clicked_doc_id", sa.Text(), nullable=True),
        sa.Column(
            "context_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_reval_events_project_created",
        "retrieval_eval_events",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_reval_events_variant_created",
        "retrieval_eval_events",
        ["variant", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_reval_events_request",
        "retrieval_eval_events",
        ["request_id"],
        unique=True,
    )

    op.create_table(
        "retrieval_eval_daily_stats",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("variant", sa.Text(), nullable=False),
        sa.Column("impressions", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("clicks", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("ctr", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "stat_date",
            "variant",
            name="uq_reval_daily_project_date_variant",
        ),
    )
    op.create_index(
        "idx_reval_daily_date_variant",
        "retrieval_eval_daily_stats",
        ["stat_date", "variant"],
        unique=False,
    )

    op.create_table(
        "embedding_job_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'success'"), nullable=False),
        sa.Column("requested", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("processed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("failed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("skipped", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("retried", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("recovered_processing", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("duration_seconds", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_embedding_job_runs_created",
        "embedding_job_runs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "idx_embedding_job_runs_status",
        "embedding_job_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "idx_embedding_job_runs_project",
        "embedding_job_runs",
        ["project_id"],
        unique=False,
    )

    op.create_table(
        "memory_rebuild_checkpoints",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_key", sa.Text(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("next_index", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'running'"), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_key",
            "project_id",
            name="uq_memory_rebuild_checkpoint_job_project",
        ),
    )
    op.create_index(
        "idx_memory_rebuild_checkpoint_status",
        "memory_rebuild_checkpoints",
        ["status"],
        unique=False,
    )
    op.create_index(
        "idx_memory_rebuild_checkpoint_updated",
        "memory_rebuild_checkpoints",
        ["updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_memory_rebuild_checkpoint_updated", table_name="memory_rebuild_checkpoints")
    op.drop_index("idx_memory_rebuild_checkpoint_status", table_name="memory_rebuild_checkpoints")
    op.drop_table("memory_rebuild_checkpoints")

    op.drop_index("idx_embedding_job_runs_project", table_name="embedding_job_runs")
    op.drop_index("idx_embedding_job_runs_status", table_name="embedding_job_runs")
    op.drop_index("idx_embedding_job_runs_created", table_name="embedding_job_runs")
    op.drop_table("embedding_job_runs")

    op.drop_index("idx_reval_daily_date_variant", table_name="retrieval_eval_daily_stats")
    op.drop_table("retrieval_eval_daily_stats")

    op.drop_index("idx_reval_events_request", table_name="retrieval_eval_events")
    op.drop_index("idx_reval_events_variant_created", table_name="retrieval_eval_events")
    op.drop_index("idx_reval_events_project_created", table_name="retrieval_eval_events")
    op.drop_table("retrieval_eval_events")

