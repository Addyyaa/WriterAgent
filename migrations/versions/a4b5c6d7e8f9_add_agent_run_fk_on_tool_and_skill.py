"""Add FK from tool_calls/skill_runs to agent_runs

Revision ID: a4b5c6d7e8f9
Revises: f2c3d4e5f6a7
Create Date: 2026-04-09 23:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, Sequence[str], None] = "f2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 先清理潜在脏数据，避免新增外键时失败。
    op.execute(
        sa.text(
            """
            UPDATE tool_calls AS t
            SET agent_run_id = NULL
            WHERE agent_run_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM agent_runs AS a WHERE a.id = t.agent_run_id
              )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE skill_runs AS s
            SET agent_run_id = NULL
            WHERE agent_run_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM agent_runs AS a WHERE a.id = s.agent_run_id
              )
            """
        )
    )

    op.create_foreign_key(
        "fk_tool_calls_agent_run_id",
        "tool_calls",
        "agent_runs",
        ["agent_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_skill_runs_agent_run_id",
        "skill_runs",
        "agent_runs",
        ["agent_run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_skill_runs_agent_run_id", "skill_runs", type_="foreignkey")
    op.drop_constraint("fk_tool_calls_agent_run_id", "tool_calls", type_="foreignkey")
