from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Float,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class RetrievalRound(Base):
    """检索轮次回放记录。"""

    __tablename__ = "retrieval_rounds"

    __table_args__ = (
        Index("idx_retrieval_rounds_run_round", "workflow_run_id", "round_index"),
        Index("idx_retrieval_rounds_trace", "retrieval_trace_id"),
        Index("idx_retrieval_rounds_step", "workflow_step_id"),
        Index("idx_retrieval_rounds_project_created", "project_id", "created_at"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    workflow_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_step_id = Column(
        BigInteger,
        ForeignKey("workflow_steps.id", ondelete="SET NULL"),
        nullable=True,
    )
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )

    trace_id = Column(Text, nullable=True)
    retrieval_trace_id = Column(Text, nullable=False)
    step_key = Column(Text, nullable=False)
    workflow_type = Column(Text, nullable=False)
    round_index = Column(Integer, nullable=False)

    query = Column(Text, nullable=False)
    intent = Column(Text, nullable=True)
    source_types_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    time_scope_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    chapter_window_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    must_have_slots_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))

    enough_context = Column(Boolean, nullable=False, server_default=text("false"))
    coverage_score = Column(Float, nullable=False, server_default=text("0"))
    new_evidence_gain = Column(Float, nullable=False, server_default=text("0"))
    stop_reason = Column(Text, nullable=True)
    latency_ms = Column(Integer, nullable=True)

    decision_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
