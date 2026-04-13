from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, Enum, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class ChapterCandidate(Base):
    __tablename__ = "chapter_candidates"

    __table_args__ = (
        Index("idx_chapter_candidates_project_status", "project_id", "status"),
        Index("idx_chapter_candidates_run", "workflow_run_id"),
        Index("idx_chapter_candidates_step", "workflow_step_id"),
        Index("idx_chapter_candidates_expires", "expires_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    workflow_run_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True)
    workflow_step_id = Column(BigInteger, ForeignKey("workflow_steps.id", ondelete="SET NULL"), nullable=True)
    agent_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True)

    chapter_no = Column(Integer, nullable=False)
    title = Column(Text, nullable=True)
    content = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)

    status = Column(
        Enum("pending", "approved", "rejected", "expired", name="chapter_candidate_status_enum"),
        nullable=False,
        server_default="pending",
    )
    expires_at = Column(DateTime(timezone=True), nullable=True)

    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    rejected_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    rejected_at = Column(DateTime(timezone=True), nullable=True)

    approved_chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True)
    approved_version_id = Column(BigInteger, ForeignKey("chapter_versions.id", ondelete="SET NULL"), nullable=True)
    memory_chunks_count = Column(Integer, nullable=False, server_default=text("0"))

    idempotency_key = Column(Text, nullable=True, unique=True)
    trace_id = Column(Text, nullable=True)
    request_id = Column(Text, nullable=True)
    metadata_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
