from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class SkillEvidence(Base):
    __tablename__ = "skill_evidence"

    __table_args__ = (
        Index("idx_skill_evidence_run", "skill_run_id"),
        Index("idx_skill_evidence_trace", "trace_id"),
        Index("idx_skill_evidence_skill", "skill_name"),
        Index("idx_skill_evidence_scope", "source_scope"),
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
    source_scope = Column(Text, nullable=True)
    evidence_type = Column(Text, nullable=True)
    payload_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
