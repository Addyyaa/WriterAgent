from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Enum, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class ProjectTransferJob(Base):
    __tablename__ = "project_transfer_jobs"

    __table_args__ = (
        Index("idx_project_transfer_jobs_project", "project_id"),
        Index("idx_project_transfer_jobs_status", "status"),
        Index("idx_project_transfer_jobs_type", "job_type"),
        Index("idx_project_transfer_jobs_created", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    job_type = Column(
        Enum("export", "import", name="project_transfer_job_type_enum"),
        nullable=False,
    )
    status = Column(
        Enum("queued", "running", "success", "failed", name="project_transfer_job_status_enum"),
        nullable=False,
        server_default="queued",
    )

    source_path = Column(Text, nullable=True)
    target_path = Column(Text, nullable=True)
    include_chapters = Column(Boolean, nullable=False, server_default=text("true"))
    include_versions = Column(Boolean, nullable=False, server_default=text("true"))
    include_long_term_memory = Column(Boolean, nullable=False, server_default=text("false"))

    size_bytes = Column(BigInteger, nullable=True)
    checksum = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    manifest_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    metadata_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
