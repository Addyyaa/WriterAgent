"""add skill findings/evidence/metrics tables for dual-write observability

Revision ID: c7d8e9f0a1b2
Revises: a9f8e7d6c5b4
Create Date: 2026-04-13 16:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, Sequence[str], None] = "a9f8e7d6c5b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "skill_findings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("skill_run_id", sa.UUID(), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("agent_run_id", sa.UUID(), nullable=True),
        sa.Column("skill_name", sa.Text(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=True),
        sa.Column("finding_type", sa.Text(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=False, server_default=sa.text("'info'")),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("evidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["skill_run_id"], ["skill_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_skill_findings_run", "skill_findings", ["skill_run_id"], unique=False)
    op.create_index("idx_skill_findings_trace", "skill_findings", ["trace_id"], unique=False)
    op.create_index("idx_skill_findings_skill", "skill_findings", ["skill_name"], unique=False)
    op.create_index("idx_skill_findings_severity", "skill_findings", ["severity"], unique=False)

    op.create_table(
        "skill_evidence",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("skill_run_id", sa.UUID(), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("agent_run_id", sa.UUID(), nullable=True),
        sa.Column("skill_name", sa.Text(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=True),
        sa.Column("source_scope", sa.Text(), nullable=True),
        sa.Column("evidence_type", sa.Text(), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["skill_run_id"], ["skill_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_skill_evidence_run", "skill_evidence", ["skill_run_id"], unique=False)
    op.create_index("idx_skill_evidence_trace", "skill_evidence", ["trace_id"], unique=False)
    op.create_index("idx_skill_evidence_skill", "skill_evidence", ["skill_name"], unique=False)
    op.create_index("idx_skill_evidence_scope", "skill_evidence", ["source_scope"], unique=False)

    op.create_table(
        "skill_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("skill_run_id", sa.UUID(), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("agent_run_id", sa.UUID(), nullable=True),
        sa.Column("skill_name", sa.Text(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=True),
        sa.Column("metric_key", sa.Text(), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=True),
        sa.Column("metric_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["skill_run_id"], ["skill_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_skill_metrics_run", "skill_metrics", ["skill_run_id"], unique=False)
    op.create_index("idx_skill_metrics_trace", "skill_metrics", ["trace_id"], unique=False)
    op.create_index("idx_skill_metrics_skill", "skill_metrics", ["skill_name"], unique=False)
    op.create_index("idx_skill_metrics_key", "skill_metrics", ["metric_key"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_skill_metrics_key", table_name="skill_metrics")
    op.drop_index("idx_skill_metrics_skill", table_name="skill_metrics")
    op.drop_index("idx_skill_metrics_trace", table_name="skill_metrics")
    op.drop_index("idx_skill_metrics_run", table_name="skill_metrics")
    op.drop_table("skill_metrics")

    op.drop_index("idx_skill_evidence_scope", table_name="skill_evidence")
    op.drop_index("idx_skill_evidence_skill", table_name="skill_evidence")
    op.drop_index("idx_skill_evidence_trace", table_name="skill_evidence")
    op.drop_index("idx_skill_evidence_run", table_name="skill_evidence")
    op.drop_table("skill_evidence")

    op.drop_index("idx_skill_findings_severity", table_name="skill_findings")
    op.drop_index("idx_skill_findings_skill", table_name="skill_findings")
    op.drop_index("idx_skill_findings_trace", table_name="skill_findings")
    op.drop_index("idx_skill_findings_run", table_name="skill_findings")
    op.drop_table("skill_findings")
