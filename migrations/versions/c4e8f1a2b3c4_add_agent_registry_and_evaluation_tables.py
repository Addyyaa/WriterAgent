"""add agent registry audit fields and unified evaluation tables

Revision ID: c4e8f1a2b3c4
Revises: b9d1e2f3a4b6
Create Date: 2026-04-10 01:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c4e8f1a2b3c4"
down_revision: Union[str, Sequence[str], None] = "b9d1e2f3a4b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for stmt in (
        "DO $$ BEGIN CREATE TYPE evaluation_type_enum AS ENUM ('retrieval', 'writing'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
        "DO $$ BEGIN CREATE TYPE evaluation_run_status_enum AS ENUM ('running', 'success', 'failed'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
    ):
        op.execute(sa.text(stmt))

    # 审计增强字段：workflow_steps / agent_runs / tool_calls / skill_runs
    op.add_column("workflow_steps", sa.Column("role_id", sa.Text(), nullable=True))
    op.add_column("workflow_steps", sa.Column("strategy_version", sa.Text(), nullable=True))
    op.add_column("workflow_steps", sa.Column("prompt_hash", sa.Text(), nullable=True))
    op.add_column("workflow_steps", sa.Column("schema_version", sa.Text(), nullable=True))
    op.create_index("idx_workflow_steps_role", "workflow_steps", ["role_id"], unique=False)

    op.add_column("agent_runs", sa.Column("role_id", sa.Text(), nullable=True))
    op.add_column("agent_runs", sa.Column("strategy_version", sa.Text(), nullable=True))
    op.add_column("agent_runs", sa.Column("prompt_hash", sa.Text(), nullable=True))
    op.add_column("agent_runs", sa.Column("schema_version", sa.Text(), nullable=True))
    op.create_index("idx_agent_role", "agent_runs", ["role_id"], unique=False)

    op.add_column("tool_calls", sa.Column("role_id", sa.Text(), nullable=True))
    op.add_column("tool_calls", sa.Column("strategy_version", sa.Text(), nullable=True))
    op.add_column("tool_calls", sa.Column("prompt_hash", sa.Text(), nullable=True))
    op.add_column("tool_calls", sa.Column("schema_version", sa.Text(), nullable=True))
    op.create_index("idx_toolcalls_role", "tool_calls", ["role_id"], unique=False)

    op.add_column("skill_runs", sa.Column("role_id", sa.Text(), nullable=True))
    op.add_column("skill_runs", sa.Column("strategy_version", sa.Text(), nullable=True))
    op.add_column("skill_runs", sa.Column("prompt_hash", sa.Text(), nullable=True))
    op.add_column("skill_runs", sa.Column("schema_version", sa.Text(), nullable=True))
    op.create_index("idx_skillruns_role", "skill_runs", ["role_id"], unique=False)

    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("workflow_run_id", sa.UUID(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column(
            "evaluation_type",
            postgresql.ENUM(
                "retrieval",
                "writing",
                name="evaluation_type_enum",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'writing'"),
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "running",
                "success",
                "failed",
                name="evaluation_run_status_enum",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'running'"),
        ),
        sa.Column("total_score", sa.Float(), nullable=True),
        sa.Column("score_breakdown_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("context_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_eval_runs_project_created", "evaluation_runs", ["project_id", "created_at"], unique=False)
    op.create_index("idx_eval_runs_type_status", "evaluation_runs", ["evaluation_type", "status"], unique=False)
    op.create_index("idx_eval_runs_workflow", "evaluation_runs", ["workflow_run_id"], unique=False)
    op.create_index("idx_eval_runs_request", "evaluation_runs", ["request_id"], unique=False)

    op.create_table(
        "evaluation_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("evaluation_run_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("workflow_run_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("metric_key", sa.Text(), nullable=True),
        sa.Column("metric_value", sa.Float(), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["evaluation_run_id"], ["evaluation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_eval_events_run_created", "evaluation_events", ["evaluation_run_id", "created_at"], unique=False)
    op.create_index("idx_eval_events_project_created", "evaluation_events", ["project_id", "created_at"], unique=False)
    op.create_index("idx_eval_events_type", "evaluation_events", ["event_type"], unique=False)
    op.create_index("idx_eval_events_metric", "evaluation_events", ["metric_key"], unique=False)

    op.create_table(
        "evaluation_daily_metrics",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("evaluation_type", sa.Text(), nullable=False),
        sa.Column("metric_key", sa.Text(), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("samples", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "metric_date",
            "evaluation_type",
            "metric_key",
            name="uq_eval_daily_project_date_type_key",
        ),
    )
    op.create_index("idx_eval_daily_project_date", "evaluation_daily_metrics", ["project_id", "metric_date"], unique=False)
    op.create_index("idx_eval_daily_type_key", "evaluation_daily_metrics", ["evaluation_type", "metric_key"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_eval_daily_type_key", table_name="evaluation_daily_metrics")
    op.drop_index("idx_eval_daily_project_date", table_name="evaluation_daily_metrics")
    op.drop_table("evaluation_daily_metrics")

    op.drop_index("idx_eval_events_metric", table_name="evaluation_events")
    op.drop_index("idx_eval_events_type", table_name="evaluation_events")
    op.drop_index("idx_eval_events_project_created", table_name="evaluation_events")
    op.drop_index("idx_eval_events_run_created", table_name="evaluation_events")
    op.drop_table("evaluation_events")

    op.drop_index("idx_eval_runs_request", table_name="evaluation_runs")
    op.drop_index("idx_eval_runs_workflow", table_name="evaluation_runs")
    op.drop_index("idx_eval_runs_type_status", table_name="evaluation_runs")
    op.drop_index("idx_eval_runs_project_created", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")

    op.drop_index("idx_skillruns_role", table_name="skill_runs")
    op.drop_column("skill_runs", "schema_version")
    op.drop_column("skill_runs", "prompt_hash")
    op.drop_column("skill_runs", "strategy_version")
    op.drop_column("skill_runs", "role_id")

    op.drop_index("idx_toolcalls_role", table_name="tool_calls")
    op.drop_column("tool_calls", "schema_version")
    op.drop_column("tool_calls", "prompt_hash")
    op.drop_column("tool_calls", "strategy_version")
    op.drop_column("tool_calls", "role_id")

    op.drop_index("idx_agent_role", table_name="agent_runs")
    op.drop_column("agent_runs", "schema_version")
    op.drop_column("agent_runs", "prompt_hash")
    op.drop_column("agent_runs", "strategy_version")
    op.drop_column("agent_runs", "role_id")

    op.drop_index("idx_workflow_steps_role", table_name="workflow_steps")
    op.drop_column("workflow_steps", "schema_version")
    op.drop_column("workflow_steps", "prompt_hash")
    op.drop_column("workflow_steps", "strategy_version")
    op.drop_column("workflow_steps", "role_id")

    for typ in ("evaluation_run_status_enum", "evaluation_type_enum"):
        op.execute(sa.text(f"DROP TYPE IF EXISTS {typ} CASCADE"))
