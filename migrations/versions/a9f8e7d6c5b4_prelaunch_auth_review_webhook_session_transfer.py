"""prelaunch auth/rbac, review gate, webhooks, sessions, backup and transfer tables

Revision ID: a9f8e7d6c5b4
Revises: e1f2a3b4c5d6
Create Date: 2026-04-11 06:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a9f8e7d6c5b4"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for stmt in (
        "DO $$ BEGIN CREATE TYPE project_membership_role_enum AS ENUM ('owner', 'editor', 'viewer'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
        "DO $$ BEGIN CREATE TYPE project_membership_status_enum AS ENUM ('active', 'invited', 'disabled'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
        "DO $$ BEGIN CREATE TYPE backup_run_type_enum AS ENUM ('full', 'incremental', 'restore_verify'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
        "DO $$ BEGIN CREATE TYPE backup_run_status_enum AS ENUM ('running', 'success', 'failed'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
        "DO $$ BEGIN CREATE TYPE webhook_subscription_status_enum AS ENUM ('active', 'paused'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
        "DO $$ BEGIN CREATE TYPE webhook_delivery_status_enum AS ENUM ('pending', 'retrying', 'success', 'dead'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
        "DO $$ BEGIN CREATE TYPE session_status_enum AS ENUM ('active', 'archived'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
        "DO $$ BEGIN CREATE TYPE session_message_role_enum AS ENUM ('system', 'user', 'assistant', 'tool'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
        "DO $$ BEGIN CREATE TYPE chapter_candidate_status_enum AS ENUM ('pending', 'approved', 'rejected', 'expired'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
        "DO $$ BEGIN CREATE TYPE project_transfer_job_type_enum AS ENUM ('export', 'import'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
        "DO $$ BEGIN CREATE TYPE project_transfer_job_status_enum AS ENUM ('queued', 'running', 'success', 'failed'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
        "DO $$ BEGIN ALTER TYPE workflow_run_status_enum ADD VALUE IF NOT EXISTS 'waiting_review'; "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
    ):
        op.execute(sa.text(stmt))

    op.create_table(
        "project_memberships",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM("owner", "editor", "viewer", name="project_membership_role_enum", create_type=False),
            nullable=False,
            server_default=sa.text("'viewer'"),
        ),
        sa.Column(
            "status",
            postgresql.ENUM("active", "invited", "disabled", name="project_membership_status_enum", create_type=False),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("invited_by", sa.UUID(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_memberships_project_user"),
    )
    op.create_index("idx_project_memberships_project_role", "project_memberships", ["project_id", "role"], unique=False)
    op.create_index("idx_project_memberships_user", "project_memberships", ["user_id"], unique=False)
    op.create_index("idx_project_memberships_status", "project_memberships", ["status"], unique=False)

    op.create_table(
        "auth_refresh_tokens",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("jti", sa.Text(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_hash", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("jti", name="uq_auth_refresh_tokens_jti"),
    )
    op.create_index("idx_auth_refresh_tokens_user", "auth_refresh_tokens", ["user_id"], unique=False)
    op.create_index("idx_auth_refresh_tokens_expires", "auth_refresh_tokens", ["expires_at"], unique=False)
    op.create_index("idx_auth_refresh_tokens_revoked", "auth_refresh_tokens", ["revoked_at"], unique=False)
    op.create_index("idx_auth_refresh_tokens_jti", "auth_refresh_tokens", ["jti"], unique=True)

    op.create_table(
        "backup_runs",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "backup_type",
            postgresql.ENUM("full", "incremental", "restore_verify", name="backup_run_type_enum", create_type=False),
            nullable=False,
            server_default=sa.text("'full'"),
        ),
        sa.Column(
            "status",
            postgresql.ENUM("running", "success", "failed", name="backup_run_status_enum", create_type=False),
            nullable=False,
            server_default=sa.text("'running'"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("checksum", sa.Text(), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_backup_runs_status", "backup_runs", ["status"], unique=False)
    op.create_index("idx_backup_runs_type", "backup_runs", ["backup_type"], unique=False)
    op.create_index("idx_backup_runs_started", "backup_runs", ["started_at"], unique=False)
    op.create_index("idx_backup_runs_created", "backup_runs", ["created_at"], unique=False)

    op.create_table(
        "webhook_subscriptions",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column("secret", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM("active", "paused", name="webhook_subscription_status_enum", create_type=False),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default=sa.text("8")),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("headers_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "event_type", "target_url", name="uq_webhook_subscription_project_event_url"),
    )
    op.create_index("idx_webhook_subscriptions_project", "webhook_subscriptions", ["project_id"], unique=False)
    op.create_index("idx_webhook_subscriptions_status", "webhook_subscriptions", ["status"], unique=False)
    op.create_index("idx_webhook_subscriptions_event", "webhook_subscriptions", ["event_type"], unique=False)

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM("pending", "retrying", "success", "dead", name="webhook_delivery_status_enum", create_type=False),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("8")),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["subscription_id"], ["webhook_subscriptions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_webhook_deliveries_event_id"),
    )
    op.create_index("idx_webhook_deliveries_status_next", "webhook_deliveries", ["status", "next_attempt_at"], unique=False)
    op.create_index("idx_webhook_deliveries_project_created", "webhook_deliveries", ["project_id", "created_at"], unique=False)
    op.create_index("idx_webhook_deliveries_subscription", "webhook_deliveries", ["subscription_id"], unique=False)
    op.create_index("idx_webhook_deliveries_event", "webhook_deliveries", ["event_type"], unique=False)
    op.create_index("idx_webhook_deliveries_event_id", "webhook_deliveries", ["event_id"], unique=True)

    op.create_table(
        "sessions",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("linked_workflow_run_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM("active", "archived", name="session_status_enum", create_type=False),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["linked_workflow_run_id"], ["workflow_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_sessions_project_updated", "sessions", ["project_id", "updated_at"], unique=False)
    op.create_index("idx_sessions_user", "sessions", ["user_id"], unique=False)
    op.create_index("idx_sessions_status", "sessions", ["status"], unique=False)

    op.create_table(
        "session_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column(
            "role",
            postgresql.ENUM("system", "user", "assistant", "tool", name="session_message_role_enum", create_type=False),
            nullable=False,
            server_default=sa.text("'user'"),
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_session_messages_session_created", "session_messages", ["session_id", "created_at"], unique=False)
    op.create_index("idx_session_messages_project_created", "session_messages", ["project_id", "created_at"], unique=False)
    op.create_index("idx_session_messages_role", "session_messages", ["role"], unique=False)

    op.create_table(
        "chapter_candidates",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("workflow_run_id", sa.UUID(), nullable=True),
        sa.Column("workflow_step_id", sa.BigInteger(), nullable=True),
        sa.Column("agent_run_id", sa.UUID(), nullable=True),
        sa.Column("chapter_no", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM("pending", "approved", "rejected", "expired", name="chapter_candidate_status_enum", create_type=False),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", sa.UUID(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_chapter_id", sa.UUID(), nullable=True),
        sa.Column("approved_version_id", sa.BigInteger(), nullable=True),
        sa.Column("memory_chunks_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workflow_step_id"], ["workflow_steps.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rejected_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_chapter_id"], ["chapters.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_version_id"], ["chapter_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_chapter_candidates_idempotency"),
    )
    op.create_index("idx_chapter_candidates_project_status", "chapter_candidates", ["project_id", "status"], unique=False)
    op.create_index("idx_chapter_candidates_run", "chapter_candidates", ["workflow_run_id"], unique=False)
    op.create_index("idx_chapter_candidates_step", "chapter_candidates", ["workflow_step_id"], unique=False)
    op.create_index("idx_chapter_candidates_expires", "chapter_candidates", ["expires_at"], unique=False)

    op.create_table(
        "project_transfer_jobs",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "job_type",
            postgresql.ENUM("export", "import", name="project_transfer_job_type_enum", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM("queued", "running", "success", "failed", name="project_transfer_job_status_enum", create_type=False),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("target_path", sa.Text(), nullable=True),
        sa.Column("include_chapters", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("include_versions", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("include_long_term_memory", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("checksum", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("manifest_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_project_transfer_jobs_project", "project_transfer_jobs", ["project_id"], unique=False)
    op.create_index("idx_project_transfer_jobs_status", "project_transfer_jobs", ["status"], unique=False)
    op.create_index("idx_project_transfer_jobs_type", "project_transfer_jobs", ["job_type"], unique=False)
    op.create_index("idx_project_transfer_jobs_created", "project_transfer_jobs", ["created_at"], unique=False)

    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_audit_events_project_created", "audit_events", ["project_id", "created_at"], unique=False)
    op.create_index("idx_audit_events_action_created", "audit_events", ["action", "created_at"], unique=False)
    op.create_index("idx_audit_events_user", "audit_events", ["user_id"], unique=False)

    op.execute(
        sa.text(
            """
            INSERT INTO project_memberships (project_id, user_id, role, status)
            SELECT p.id, p.owner_user_id, 'owner', 'active'
            FROM projects p
            WHERE p.owner_user_id IS NOT NULL
            ON CONFLICT (project_id, user_id) DO UPDATE
            SET role = EXCLUDED.role,
                status = EXCLUDED.status,
                updated_at = now();
            """
        )
    )


def downgrade() -> None:
    op.drop_index("idx_audit_events_user", table_name="audit_events")
    op.drop_index("idx_audit_events_action_created", table_name="audit_events")
    op.drop_index("idx_audit_events_project_created", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("idx_project_transfer_jobs_created", table_name="project_transfer_jobs")
    op.drop_index("idx_project_transfer_jobs_type", table_name="project_transfer_jobs")
    op.drop_index("idx_project_transfer_jobs_status", table_name="project_transfer_jobs")
    op.drop_index("idx_project_transfer_jobs_project", table_name="project_transfer_jobs")
    op.drop_table("project_transfer_jobs")

    op.drop_index("idx_chapter_candidates_expires", table_name="chapter_candidates")
    op.drop_index("idx_chapter_candidates_step", table_name="chapter_candidates")
    op.drop_index("idx_chapter_candidates_run", table_name="chapter_candidates")
    op.drop_index("idx_chapter_candidates_project_status", table_name="chapter_candidates")
    op.drop_table("chapter_candidates")

    op.drop_index("idx_session_messages_role", table_name="session_messages")
    op.drop_index("idx_session_messages_project_created", table_name="session_messages")
    op.drop_index("idx_session_messages_session_created", table_name="session_messages")
    op.drop_table("session_messages")

    op.drop_index("idx_sessions_status", table_name="sessions")
    op.drop_index("idx_sessions_user", table_name="sessions")
    op.drop_index("idx_sessions_project_updated", table_name="sessions")
    op.drop_table("sessions")

    op.drop_index("idx_webhook_deliveries_event_id", table_name="webhook_deliveries")
    op.drop_index("idx_webhook_deliveries_event", table_name="webhook_deliveries")
    op.drop_index("idx_webhook_deliveries_subscription", table_name="webhook_deliveries")
    op.drop_index("idx_webhook_deliveries_project_created", table_name="webhook_deliveries")
    op.drop_index("idx_webhook_deliveries_status_next", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")

    op.drop_index("idx_webhook_subscriptions_event", table_name="webhook_subscriptions")
    op.drop_index("idx_webhook_subscriptions_status", table_name="webhook_subscriptions")
    op.drop_index("idx_webhook_subscriptions_project", table_name="webhook_subscriptions")
    op.drop_table("webhook_subscriptions")

    op.drop_index("idx_backup_runs_created", table_name="backup_runs")
    op.drop_index("idx_backup_runs_started", table_name="backup_runs")
    op.drop_index("idx_backup_runs_type", table_name="backup_runs")
    op.drop_index("idx_backup_runs_status", table_name="backup_runs")
    op.drop_table("backup_runs")

    op.drop_index("idx_auth_refresh_tokens_jti", table_name="auth_refresh_tokens")
    op.drop_index("idx_auth_refresh_tokens_revoked", table_name="auth_refresh_tokens")
    op.drop_index("idx_auth_refresh_tokens_expires", table_name="auth_refresh_tokens")
    op.drop_index("idx_auth_refresh_tokens_user", table_name="auth_refresh_tokens")
    op.drop_table("auth_refresh_tokens")

    op.drop_index("idx_project_memberships_status", table_name="project_memberships")
    op.drop_index("idx_project_memberships_user", table_name="project_memberships")
    op.drop_index("idx_project_memberships_project_role", table_name="project_memberships")
    op.drop_table("project_memberships")

    # workflow_run_status_enum 新增值 waiting_review 不在 downgrade 中移除（PostgreSQL 不支持安全删除 enum value）。

    for typ in (
        "project_transfer_job_status_enum",
        "project_transfer_job_type_enum",
        "chapter_candidate_status_enum",
        "session_message_role_enum",
        "session_status_enum",
        "webhook_delivery_status_enum",
        "webhook_subscription_status_enum",
        "backup_run_status_enum",
        "backup_run_type_enum",
        "project_membership_status_enum",
        "project_membership_role_enum",
    ):
        op.execute(sa.text(f"DROP TYPE IF EXISTS {typ} CASCADE"))
