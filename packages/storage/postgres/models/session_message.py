from __future__ import annotations

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class SessionMessage(Base):
    __tablename__ = "session_messages"

    __table_args__ = (
        Index("idx_session_messages_session_created", "session_id", "created_at"),
        Index("idx_session_messages_project_created", "project_id", "created_at"),
        Index("idx_session_messages_role", "role"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    role = Column(
        Enum("system", "user", "assistant", "tool", name="session_message_role_enum"),
        nullable=False,
        server_default="user",
    )
    content = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=True)
    metadata_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
