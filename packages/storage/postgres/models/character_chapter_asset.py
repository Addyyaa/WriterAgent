"""角色在指定章节下的物品与财富快照（用于创作一致性与 UI 展示）。"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class CharacterChapterAsset(Base):
    __tablename__ = "character_chapter_assets"

    __table_args__ = (
        UniqueConstraint("character_id", "chapter_no", name="uq_character_chapter_assets_char_chapter"),
        Index("idx_character_chapter_assets_character", "character_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    character_id = Column(
        UUID(as_uuid=True),
        ForeignKey("characters.id", ondelete="CASCADE"),
        nullable=False,
    )
    chapter_no = Column(Integer, nullable=False)
    inventory_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    wealth_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
