from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, Float, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class SkillMetric(Base):
    __tablename__ = "skill_metrics"

    __table_args__ = (
        Index("idx_skill_metrics_run", "skill_run_id"),
        Index("idx_skill_metrics_trace", "trace_id"),
        Index("idx_skill_metrics_skill", "skill_name"),
        Index("idx_skill_metrics_key", "metric_key"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    skill_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("skill_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    trace_id = Column(Text, nullable=True)
    agent_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    skill_name = Column(Text, nullable=False)
    phase = Column(Text, nullable=True)
    metric_key = Column(Text, nullable=False)
    metric_value = Column(Float, nullable=True)
    metric_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
