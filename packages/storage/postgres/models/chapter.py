"""
章节（Chapter）的 PostgreSQL ORM 模型（工程级版本）。

用于按项目存储章节序号、正文与摘要、发布状态及草稿版本。
"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    Index,
    func,
    text,
    Enum,
)
from sqlalchemy.dialects.postgresql import UUID

from ..base import Base


class Chapter(Base):
    __tablename__ = "chapters"

    __table_args__ = (
        # 同一项目下章节号唯一
        UniqueConstraint(
            "project_id",
            "chapter_no",
            name="uq_chapters_project_id_chapter_no",
        ),
        # 查询章节优化
        Index("idx_chapters_project", "project_id"),
        Index("idx_chapters_status", "status"),
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
    # 章节信息
    # ========================
    chapter_no = Column(Integer, nullable=False)
    title = Column(Text, nullable=True)
    content = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)

    # ========================
    # 状态与版本
    # ========================
    status = Column(
        Enum("draft", "published", name="chapter_status_enum"),
        nullable=False,
        server_default="draft",
    )
    draft_version = Column(Integer, nullable=False, server_default=text("1"))

    # ========================
    # 创建者
    # ========================
    created_by = Column(UUID(as_uuid=True), nullable=True)

    # ========================
    # 时间
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