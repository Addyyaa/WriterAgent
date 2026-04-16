"""章节定稿后的故事状态快照（续写时优先读取，减少对长正文的反复推断）。"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class StoryStateSnapshot(Base):
    __tablename__ = "story_state_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "chapter_no",
            name="uq_story_state_snapshots_project_chapter",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    chapter_no = Column(Integer, nullable=False)
    state_json = Column(JSONB(astext_type=Text()), nullable=False, server_default=text("'{}'::jsonb"))
    source = Column(String(64), nullable=False, server_default="candidate_approve")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
