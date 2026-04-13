"""
章节版本快照（ChapterVersion）的 PostgreSQL ORM 模型（工程级版本）。

用于保存不可变版本历史，支持版本回溯、追踪源 Agent 与 workflow。
"""

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    Index,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from ..base import Base


class ChapterVersion(Base):
    __tablename__ = "chapter_versions"

    __table_args__ = (
        # 同一章节下 version_no 唯一
        UniqueConstraint(
            "chapter_id",
            "version_no",
            name="uq_chapter_versions_chapter_id_version_no",
        ),
        # 查询章节所有版本优化
        Index("idx_chapter_versions_chapter_id", "chapter_id"),
    )

    # ========================
    # 主键
    # ========================
    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # ========================
    # 外键关联章节
    # ========================
    chapter_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,  # 🔥 必须
    )

    # ========================
    # 版本号
    # ========================
    version_no = Column(Integer, nullable=False)

    # ========================
    # 章节内容
    # ========================
    content = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)

    # ========================
    # 来源追踪
    # ========================
    source_agent = Column(Text, nullable=True)
    source_workflow = Column(Text, nullable=True)
    trace_id = Column(Text, nullable=True)

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