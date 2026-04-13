from __future__ import annotations

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Index, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class EvaluationDailyMetric(Base):
    """评测日报聚合结果。"""

    __tablename__ = "evaluation_daily_metrics"

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "metric_date",
            "evaluation_type",
            "metric_key",
            name="uq_eval_daily_project_date_type_key",
        ),
        Index("idx_eval_daily_project_date", "project_id", "metric_date"),
        Index("idx_eval_daily_type_key", "evaluation_type", "metric_key"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    metric_date = Column(Date, nullable=False)
    evaluation_type = Column(Text, nullable=False)
    metric_key = Column(Text, nullable=False)
    metric_value = Column(Float, nullable=False, server_default=text("0"))
    samples = Column(Integer, nullable=False, server_default=text("0"))
    metadata_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
