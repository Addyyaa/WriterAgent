"""add orchestrator and full workflow tables

Revision ID: b9d1e2f3a4b6
Revises: a4b5c6d7e8f9
Create Date: 2026-04-09 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b9d1e2f3a4b6"
down_revision: Union[str, Sequence[str], None] = "a4b5c6d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for stmt in (
        "DO $$ BEGIN CREATE TYPE workflow_run_status_enum AS ENUM "
        "('queued', 'running', 'success', 'failed', 'cancelled'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
        "DO $$ BEGIN CREATE TYPE workflow_step_status_enum AS ENUM "
        "('pending', 'queued', 'running', 'success', 'failed', 'skipped', 'cancelled'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
        "DO $$ BEGIN CREATE TYPE agent_message_role_enum AS ENUM "
        "('system', 'user', 'assistant', 'tool', 'planner'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
        "DO $$ BEGIN CREATE TYPE consistency_report_status_enum AS ENUM "
        "('passed', 'warning', 'failed'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
    ):
        op.execute(sa.text(stmt))

    op.add_column("projects", sa.Column("owner_user_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_projects_owner_user",
        source_table="projects",
        referent_table="users",
        local_cols=["owner_user_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_projects_owner_user", "projects", ["owner_user_id"], unique=False)

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("initiated_by", sa.UUID(), nullable=True),
        sa.Column("parent_run_id", sa.UUID(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("workflow_type", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "queued",
                "running",
                "success",
                "failed",
                "cancelled",
                name="workflow_run_status_enum",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default=sa.text("2")),
        sa.Column("input_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("plan_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["initiated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parent_run_id"], ["workflow_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_workflow_runs_project", "workflow_runs", ["project_id"], unique=False)
    op.create_index("idx_workflow_runs_status", "workflow_runs", ["status"], unique=False)
    op.create_index("idx_workflow_runs_type", "workflow_runs", ["workflow_type"], unique=False)
    op.create_index("idx_workflow_runs_queue", "workflow_runs", ["status", "next_attempt_at"], unique=False)
    op.create_index("idx_workflow_runs_trace", "workflow_runs", ["trace_id"], unique=False)
    op.create_index("idx_workflow_runs_idempotency", "workflow_runs", ["idempotency_key"], unique=True)

    op.create_table(
        "workflow_steps",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("workflow_run_id", sa.UUID(), nullable=False),
        sa.Column("step_key", sa.Text(), nullable=False),
        sa.Column("step_type", sa.Text(), nullable=False),
        sa.Column("agent_name", sa.Text(), nullable=True),
        sa.Column("depends_on_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("input_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "queued",
                "running",
                "success",
                "failed",
                "skipped",
                "cancelled",
                name="workflow_step_status_enum",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_run_id", "step_key", name="uq_workflow_steps_run_step_key"),
    )
    op.create_index("idx_workflow_steps_run", "workflow_steps", ["workflow_run_id"], unique=False)
    op.create_index("idx_workflow_steps_status", "workflow_steps", ["status"], unique=False)
    op.create_index("idx_workflow_steps_agent", "workflow_steps", ["agent_name"], unique=False)

    op.create_table(
        "agent_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("workflow_run_id", sa.UUID(), nullable=False),
        sa.Column("workflow_step_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "role",
            postgresql.ENUM(
                "system",
                "user",
                "assistant",
                "tool",
                "planner",
                name="agent_message_role_enum",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'assistant'"),
        ),
        sa.Column("sender", sa.Text(), nullable=True),
        sa.Column("receiver", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_step_id"], ["workflow_steps.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_agent_messages_run_created", "agent_messages", ["workflow_run_id", "created_at"], unique=False)
    op.create_index("idx_agent_messages_step", "agent_messages", ["workflow_step_id"], unique=False)
    op.create_index("idx_agent_messages_role", "agent_messages", ["role"], unique=False)

    op.create_table(
        "outlines",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("structure_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source_agent", sa.Text(), nullable=True),
        sa.Column("source_workflow", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "version_no", name="uq_outlines_project_version"),
    )
    op.create_index("idx_outlines_project_active", "outlines", ["project_id", "is_active"], unique=False)
    op.create_index("idx_outlines_trace", "outlines", ["trace_id"], unique=False)

    op.create_table(
        "consistency_reports",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("chapter_id", sa.UUID(), nullable=True),
        sa.Column("chapter_version_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "passed",
                "warning",
                "failed",
                name="consistency_report_status_enum",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'warning'"),
        ),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("issues_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("recommendations_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("source_agent", sa.Text(), nullable=True),
        sa.Column("source_workflow", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["chapter_version_id"], ["chapter_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_consistency_reports_project_created", "consistency_reports", ["project_id", "created_at"], unique=False)
    op.create_index("idx_consistency_reports_status", "consistency_reports", ["status"], unique=False)
    op.create_index("idx_consistency_reports_chapter", "consistency_reports", ["chapter_id", "chapter_version_id"], unique=False)
    op.create_index("idx_consistency_reports_trace", "consistency_reports", ["trace_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_consistency_reports_trace", table_name="consistency_reports")
    op.drop_index("idx_consistency_reports_chapter", table_name="consistency_reports")
    op.drop_index("idx_consistency_reports_status", table_name="consistency_reports")
    op.drop_index("idx_consistency_reports_project_created", table_name="consistency_reports")
    op.drop_table("consistency_reports")

    op.drop_index("idx_outlines_trace", table_name="outlines")
    op.drop_index("idx_outlines_project_active", table_name="outlines")
    op.drop_table("outlines")

    op.drop_index("idx_agent_messages_role", table_name="agent_messages")
    op.drop_index("idx_agent_messages_step", table_name="agent_messages")
    op.drop_index("idx_agent_messages_run_created", table_name="agent_messages")
    op.drop_table("agent_messages")

    op.drop_index("idx_workflow_steps_agent", table_name="workflow_steps")
    op.drop_index("idx_workflow_steps_status", table_name="workflow_steps")
    op.drop_index("idx_workflow_steps_run", table_name="workflow_steps")
    op.drop_table("workflow_steps")

    op.drop_index("idx_workflow_runs_idempotency", table_name="workflow_runs")
    op.drop_index("idx_workflow_runs_trace", table_name="workflow_runs")
    op.drop_index("idx_workflow_runs_queue", table_name="workflow_runs")
    op.drop_index("idx_workflow_runs_type", table_name="workflow_runs")
    op.drop_index("idx_workflow_runs_status", table_name="workflow_runs")
    op.drop_index("idx_workflow_runs_project", table_name="workflow_runs")
    op.drop_table("workflow_runs")

    op.drop_index("idx_projects_owner_user", table_name="projects")
    op.drop_constraint("fk_projects_owner_user", "projects", type_="foreignkey")
    op.drop_column("projects", "owner_user_id")

    for typ in (
        "consistency_report_status_enum",
        "agent_message_role_enum",
        "workflow_step_status_enum",
        "workflow_run_status_enum",
    ):
        op.execute(sa.text(f"DROP TYPE IF EXISTS {typ} CASCADE"))
