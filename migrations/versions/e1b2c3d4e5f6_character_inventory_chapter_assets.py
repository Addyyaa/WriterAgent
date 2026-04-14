"""角色物品/财富与按章节快照

Revision ID: e1b2c3d4e5f6
Revises: c7d8e9f0a1b2
Create Date: 2026-04-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "characters",
        sa.Column("inventory_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.add_column(
        "characters",
        sa.Column("wealth_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )

    op.create_table(
        "character_chapter_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("character_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chapter_no", sa.Integer(), nullable=False),
        sa.Column("inventory_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("wealth_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("character_id", "chapter_no", name="uq_character_chapter_assets_char_chapter"),
    )
    op.create_index("idx_character_chapter_assets_character", "character_chapter_assets", ["character_id"])


def downgrade() -> None:
    op.drop_index("idx_character_chapter_assets_character", table_name="character_chapter_assets")
    op.drop_table("character_chapter_assets")
    op.drop_column("characters", "wealth_json")
    op.drop_column("characters", "inventory_json")
