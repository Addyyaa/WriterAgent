"""
伏笔（Foreshadowing）的 PostgreSQL ORM 模型（工程级版本）。

用于按项目记录铺垫章节、预期回收与实际回收信息，以及伏笔状态。
"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    func,
    text,
    Enum,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID

from ..base import Base


class Foreshadowing(Base):
    __tablename__ = "foreshadowings"

    __table_args__ = (
        # 按项目查询性能优化
        Index("idx_foreshadowings_project", "project_id"),
        Index("idx_foreshadowings_status", "status"),
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
    # 铺垫章节信息
    # ========================
    setup_chapter_no = Column(Integer, nullable=True)
    setup_text = Column(Text, nullable=True)

    # ========================
    # 预期回收
    # ========================
    expected_payoff = Column(Text, nullable=True)

    # ========================
    # 实际回收
    # ========================
    payoff_chapter_no = Column(Integer, nullable=True)
    payoff_text = Column(Text, nullable=True)

    # ========================
    # 状态
    # ========================
    status = Column(
        Enum("open", "resolved", name="foreshadowing_status_enum"),
        nullable=False,
        server_default="open",
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