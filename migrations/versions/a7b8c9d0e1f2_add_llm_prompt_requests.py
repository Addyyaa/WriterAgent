"""add llm_prompt_requests for ops audit of agent→LLM context

Revision ID: a7b8c9d0e1f2
Revises: f3a4b5c6d7e8
Create Date: 2026-04-15 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_prompt_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("workflow_run_id", sa.UUID(), nullable=True),
        sa.Column("workflow_step_id", sa.UUID(), nullable=True),
        sa.Column("role_id", sa.Text(), nullable=True),
        sa.Column("step_key", sa.Text(), nullable=True),
        sa.Column("workflow_type", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("provider_label", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("user_prompt", sa.Text(), nullable=False),
        sa.Column("system_chars", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("user_chars", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("prompt_guard_applied", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_llm_prompt_requests_trace_created",
        "llm_prompt_requests",
        ["trace_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_llm_prompt_requests_run_created",
        "llm_prompt_requests",
        ["workflow_run_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_llm_prompt_requests_run_created", table_name="llm_prompt_requests")
    op.drop_index("idx_llm_prompt_requests_trace_created", table_name="llm_prompt_requests")
    op.drop_table("llm_prompt_requests")
