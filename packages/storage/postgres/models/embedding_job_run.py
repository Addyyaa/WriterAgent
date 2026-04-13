from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class EmbeddingJobRun(Base):
    """Embedding 作业运行记录。"""

    __tablename__ = "embedding_job_runs"

    __table_args__ = (
        Index("idx_embedding_job_runs_created", "created_at"),
        Index("idx_embedding_job_runs_status", "status"),
        Index("idx_embedding_job_runs_project", "project_id"),
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    status = Column(Text, nullable=False, server_default=text("'success'"))
    requested = Column(Integer, nullable=False, server_default=text("0"))
    processed = Column(Integer, nullable=False, server_default=text("0"))
    failed = Column(Integer, nullable=False, server_default=text("0"))
    skipped = Column(Integer, nullable=False, server_default=text("0"))
    retried = Column(Integer, nullable=False, server_default=text("0"))
    recovered_processing = Column(Integer, nullable=False, server_default=text("0"))
    duration_seconds = Column(Float, nullable=False, server_default=text("0"))
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=False)
    error_message = Column(Text, nullable=True)
    metadata_json = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
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

