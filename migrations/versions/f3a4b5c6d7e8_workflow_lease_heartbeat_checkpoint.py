"""workflow_runs 租约/心跳；workflow_steps 心跳与 checkpoint_json

Revision ID: f3a4b5c6d7e8
Revises: e1b2c3d4e5f6
Create Date: 2026-04-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, Sequence[str], None] = "e1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workflow_runs", sa.Column("claimed_by", sa.Text(), nullable=True))
    op.add_column("workflow_runs", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("workflow_runs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("workflow_runs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("workflow_steps", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("workflow_steps", sa.Column("last_progress_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "workflow_steps",
        sa.Column(
            "checkpoint_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("workflow_steps", "checkpoint_json")
    op.drop_column("workflow_steps", "last_progress_at")
    op.drop_column("workflow_steps", "heartbeat_at")
    op.drop_column("workflow_runs", "lease_expires_at")
    op.drop_column("workflow_runs", "heartbeat_at")
    op.drop_column("workflow_runs", "claimed_at")
    op.drop_column("workflow_runs", "claimed_by")
