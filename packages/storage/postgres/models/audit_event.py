from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"

    __table_args__ = (
        Index("idx_audit_events_project_created", "project_id", "created_at"),
        Index("idx_audit_events_action_created", "action", "created_at"),
        Index("idx_audit_events_user", "user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    action = Column(Text, nullable=False)
    resource_type = Column(Text, nullable=False)
    resource_id = Column(Text, nullable=True)

    trace_id = Column(Text, nullable=True)
    request_id = Column(Text, nullable=True)
    payload_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
