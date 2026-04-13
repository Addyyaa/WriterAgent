from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class RetrievalEvidenceItem(Base):
    """检索证据明细。"""

    __tablename__ = "retrieval_evidence_items"

    __table_args__ = (
        Index("idx_retrieval_evidence_round", "retrieval_round_id"),
        Index("idx_retrieval_evidence_run_round", "workflow_run_id", "round_index"),
        Index("idx_retrieval_evidence_trace", "retrieval_trace_id"),
        Index("idx_retrieval_evidence_source", "source_type", "source_id"),
        Index("idx_retrieval_evidence_project_created", "project_id", "created_at"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    retrieval_round_id = Column(
        BigInteger,
        ForeignKey("retrieval_rounds.id", ondelete="CASCADE"),
        nullable=False,
    )
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
    round_index = Column(Integer, nullable=False)

    source_type = Column(Text, nullable=False)
    source_id = Column(Text, nullable=True)
    chunk_id = Column(Text, nullable=True)
    score = Column(Float, nullable=True)
    adopted = Column(Boolean, nullable=False, server_default=text("true"))
    evidence_text = Column(Text, nullable=False)
    metadata_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
