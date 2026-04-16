"""合并迁移：story_state_snapshots 与 llm_prompt_requests 两条分支

Revision ID: b0c1d2e3f4a5
Revises: a7b8c9d0e1f2, f1a2b3c4d5e7
Create Date: 2026-04-15
"""

from typing import Sequence, Union


revision: str = "b0c1d2e3f4a5"
down_revision: Union[str, Sequence[str], None] = ("a7b8c9d0e1f2", "f1a2b3c4d5e7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
