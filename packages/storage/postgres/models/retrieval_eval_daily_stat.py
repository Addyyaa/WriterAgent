from __future__ import annotations

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from ..base import Base


class RetrievalEvalDailyStat(Base):
    """检索在线评测日聚合统计。"""

    __tablename__ = "retrieval_eval_daily_stats"

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "stat_date",
            "variant",
            name="uq_reval_daily_project_date_variant",
        ),
        Index("idx_reval_daily_date_variant", "stat_date", "variant"),
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    stat_date = Column(Date, nullable=False)
    variant = Column(Text, nullable=False)
    impressions = Column(Integer, nullable=False, server_default=text("0"))
    clicks = Column(Integer, nullable=False, server_default=text("0"))
    ctr = Column(Float, nullable=False, server_default=text("0"))
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
