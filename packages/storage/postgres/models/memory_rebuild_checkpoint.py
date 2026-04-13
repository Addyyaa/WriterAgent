from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class MemoryRebuildCheckpoint(Base):
    """长期记忆重建断点持久化。"""

    __tablename__ = "memory_rebuild_checkpoints"

    __table_args__ = (
        UniqueConstraint(
            "job_key",
            "project_id",
            name="uq_memory_rebuild_checkpoint_job_project",
        ),
        Index("idx_memory_rebuild_checkpoint_status", "status"),
        Index("idx_memory_rebuild_checkpoint_updated", "updated_at"),
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    job_key = Column(Text, nullable=False)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    next_index = Column(Integer, nullable=False, server_default=text("0"))
    status = Column(Text, nullable=False, server_default=text("'running'"))
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

