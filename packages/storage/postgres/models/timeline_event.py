"""
时间线事件（TimelineEvent）的 PostgreSQL ORM 模型（工程级版本）。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class TimelineEvent(Base):
    __tablename__ = "timeline_events"

    __table_args__ = (
        Index("idx_timeline_project", "project_id"),
    )

    # ========================
    # 主键
    # ========================
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    # ========================
    # 项目关联
    # ========================
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,  # 🔥 必须
    )

    # ========================
    # 章节关联
    # ========================
    chapter_no = Column(Integer, nullable=True)

    # ========================
    # 事件信息
    # ========================
    event_title = Column(Text, nullable=True)
    event_desc = Column(Text, nullable=True)
    location = Column(Text, nullable=True)

    # ========================
    # JSONB 扩展字段
    # ========================
    involved_characters = Column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    causal_links = Column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )

    # ========================
    # 时间字段
    # ========================
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )