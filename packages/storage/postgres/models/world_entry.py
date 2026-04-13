"""
世界观条目（WorldEntry）的 PostgreSQL ORM 模型（工程级版本）。
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class WorldEntry(Base):
    __tablename__ = "world_entries"

    __table_args__ = (
        Index("idx_worldentries_project", "project_id"),
        Index("idx_worldentries_entry_type", "entry_type"),
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
    # 条目信息
    # ========================
    entry_type = Column(Text, nullable=True)
    title = Column(Text, nullable=True)
    content = Column(Text, nullable=True)

    # ========================
    # 扩展元数据
    # ========================
    metadata_json = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    # ========================
    # 版本与正史
    # ========================
    version = Column(Integer, nullable=False, server_default=text("1"))
    is_canonical = Column(Boolean, nullable=False, server_default=text("true"))

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