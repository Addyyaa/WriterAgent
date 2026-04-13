"""
写作项目（Project）的 PostgreSQL ORM 模型（工程级版本）。
"""

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import UUID, JSONB

from ..base import Base


class Project(Base):
    __tablename__ = "projects"

    # ========================
    # 主键
    # ========================
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    # ========================
    # 核心信息
    # ========================
    owner_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    title = Column(String, nullable=False)
    genre = Column(String, nullable=True)
    premise = Column(Text, nullable=True)

    # ========================
    # 扩展元数据
    # ========================
    metadata_json = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
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
