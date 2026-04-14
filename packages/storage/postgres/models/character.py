"""
角色（Character）的 PostgreSQL ORM 模型（工程级版本）。

用于故事角色管理，支持版本控制、正史标记和 JSONB 扩展字段。
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


class Character(Base):
    __tablename__ = "characters"

    __table_args__ = (
        Index("idx_characters_project", "project_id"),
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
    # 角色信息
    # ========================
    name = Column(Text, nullable=False)
    role_type = Column(Text, nullable=True)
    age = Column(Integer, nullable=True)
    faction = Column(Text, nullable=True)

    # ========================
    # JSONB 扩展字段
    # ========================
    profile_json = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    speech_style_json = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    arc_status_json = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    inventory_json = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    wealth_json = Column(
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