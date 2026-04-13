from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, Enum, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class AgentMessage(Base):
    """多 Agent 交互消息日志。"""

    __tablename__ = "agent_messages"

    __table_args__ = (
        Index("idx_agent_messages_run_created", "workflow_run_id", "created_at"),
        Index("idx_agent_messages_step", "workflow_step_id"),
        Index("idx_agent_messages_role", "role"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)

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

    role = Column(
        Enum(
            "system",
            "user",
            "assistant",
            "tool",
            "planner",
            name="agent_message_role_enum",
        ),
        nullable=False,
        server_default="assistant",
    )
    sender = Column(Text, nullable=True)
    receiver = Column(Text, nullable=True)
    content = Column(Text, nullable=False)
    metadata_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
