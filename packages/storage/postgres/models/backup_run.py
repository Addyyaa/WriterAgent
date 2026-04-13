from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, Enum, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class BackupRun(Base):
    __tablename__ = "backup_runs"

    __table_args__ = (
        Index("idx_backup_runs_status", "status"),
        Index("idx_backup_runs_type", "backup_type"),
        Index("idx_backup_runs_started", "started_at"),
        Index("idx_backup_runs_created", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))

    backup_type = Column(
        Enum("full", "incremental", "restore_verify", name="backup_run_type_enum"),
        nullable=False,
        server_default="full",
    )
    status = Column(
        Enum("running", "success", "failed", name="backup_run_status_enum"),
        nullable=False,
        server_default="running",
    )

    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)

    size_bytes = Column(BigInteger, nullable=True)
    checksum = Column(Text, nullable=True)
    file_path = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    metadata_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
