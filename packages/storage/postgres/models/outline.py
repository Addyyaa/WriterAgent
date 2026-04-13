from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class Outline(Base):
    """项目大纲版本。"""

    __tablename__ = "outlines"

    __table_args__ = (
        UniqueConstraint("project_id", "version_no", name="uq_outlines_project_version"),
        Index("idx_outlines_project_active", "project_id", "is_active"),
        Index("idx_outlines_trace", "trace_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )

    version_no = Column(Integer, nullable=False)
    title = Column(Text, nullable=True)
    content = Column(Text, nullable=True)
    structure_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    source_agent = Column(Text, nullable=True)
    source_workflow = Column(Text, nullable=True)
    trace_id = Column(Text, nullable=True)

    is_active = Column(Boolean, nullable=False, server_default=text("true"))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
