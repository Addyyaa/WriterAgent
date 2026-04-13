from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, Float, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class EvaluationEvent(Base):
    """评测事件流（在线打点 + 用户反馈 + 聚合输入）。"""

    __tablename__ = "evaluation_events"

    __table_args__ = (
        Index("idx_eval_events_run_created", "evaluation_run_id", "created_at"),
        Index("idx_eval_events_project_created", "project_id", "created_at"),
        Index("idx_eval_events_type", "event_type"),
        Index("idx_eval_events_metric", "metric_key"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    evaluation_run_id = Column(UUID(as_uuid=True), ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    workflow_run_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True)

    event_type = Column(Text, nullable=False)
    metric_key = Column(Text, nullable=True)
    metric_value = Column(Float, nullable=True)
    payload_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
