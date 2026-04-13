from __future__ import annotations

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class SessionModel(Base):
    __tablename__ = "sessions"

    __table_args__ = (
        Index("idx_sessions_project_updated", "project_id", "updated_at"),
        Index("idx_sessions_user", "user_id"),
        Index("idx_sessions_status", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    linked_workflow_run_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True)

    title = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    status = Column(
        Enum("active", "archived", name="session_status_enum"),
        nullable=False,
        server_default="active",
    )
    metadata_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
