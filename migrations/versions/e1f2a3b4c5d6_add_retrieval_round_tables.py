"""add retrieval round replay tables

Revision ID: e1f2a3b4c5d6
Revises: d8e9f0a1b2c3
Create Date: 2026-04-10 12:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d8e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "retrieval_rounds",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("workflow_run_id", sa.UUID(), nullable=False),
        sa.Column("workflow_step_id", sa.BigInteger(), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("retrieval_trace_id", sa.Text(), nullable=False),
        sa.Column("step_key", sa.Text(), nullable=False),
        sa.Column("workflow_type", sa.Text(), nullable=False),
        sa.Column("round_index", sa.Integer(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("intent", sa.Text(), nullable=True),
        sa.Column("source_types_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("time_scope_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("chapter_window_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("must_have_slots_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("enough_context", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("coverage_score", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("new_evidence_gain", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("stop_reason", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("decision_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_step_id"], ["workflow_steps.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_retrieval_rounds_run_round", "retrieval_rounds", ["workflow_run_id", "round_index"], unique=False)
    op.create_index("idx_retrieval_rounds_trace", "retrieval_rounds", ["retrieval_trace_id"], unique=False)
    op.create_index("idx_retrieval_rounds_step", "retrieval_rounds", ["workflow_step_id"], unique=False)
    op.create_index("idx_retrieval_rounds_project_created", "retrieval_rounds", ["project_id", "created_at"], unique=False)

    op.create_table(
        "retrieval_evidence_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("retrieval_round_id", sa.BigInteger(), nullable=False),
        sa.Column("workflow_run_id", sa.UUID(), nullable=False),
        sa.Column("workflow_step_id", sa.BigInteger(), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("retrieval_trace_id", sa.Text(), nullable=False),
        sa.Column("step_key", sa.Text(), nullable=False),
        sa.Column("round_index", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=True),
        sa.Column("chunk_id", sa.Text(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("adopted", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("evidence_text", sa.Text(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["retrieval_round_id"], ["retrieval_rounds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_step_id"], ["workflow_steps.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_retrieval_evidence_round", "retrieval_evidence_items", ["retrieval_round_id"], unique=False)
    op.create_index("idx_retrieval_evidence_run_round", "retrieval_evidence_items", ["workflow_run_id", "round_index"], unique=False)
    op.create_index("idx_retrieval_evidence_trace", "retrieval_evidence_items", ["retrieval_trace_id"], unique=False)
    op.create_index("idx_retrieval_evidence_source", "retrieval_evidence_items", ["source_type", "source_id"], unique=False)
    op.create_index("idx_retrieval_evidence_project_created", "retrieval_evidence_items", ["project_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_retrieval_evidence_project_created", table_name="retrieval_evidence_items")
    op.drop_index("idx_retrieval_evidence_source", table_name="retrieval_evidence_items")
    op.drop_index("idx_retrieval_evidence_trace", table_name="retrieval_evidence_items")
    op.drop_index("idx_retrieval_evidence_run_round", table_name="retrieval_evidence_items")
    op.drop_index("idx_retrieval_evidence_round", table_name="retrieval_evidence_items")
    op.drop_table("retrieval_evidence_items")

    op.drop_index("idx_retrieval_rounds_project_created", table_name="retrieval_rounds")
    op.drop_index("idx_retrieval_rounds_step", table_name="retrieval_rounds")
    op.drop_index("idx_retrieval_rounds_trace", table_name="retrieval_rounds")
    op.drop_index("idx_retrieval_rounds_run_round", table_name="retrieval_rounds")
    op.drop_table("retrieval_rounds")
