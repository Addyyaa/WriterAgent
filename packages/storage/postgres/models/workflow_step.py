from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class WorkflowStep(Base):
    """工作流步骤状态。"""

    __tablename__ = "workflow_steps"

    __table_args__ = (
        UniqueConstraint("workflow_run_id", "step_key", name="uq_workflow_steps_run_step_key"),
        Index("idx_workflow_steps_run", "workflow_run_id"),
        Index("idx_workflow_steps_status", "status"),
        Index("idx_workflow_steps_agent", "agent_name"),
        Index("idx_workflow_steps_role", "role_id"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    workflow_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    step_key = Column(Text, nullable=False)
    step_type = Column(Text, nullable=False)
    agent_name = Column(Text, nullable=True)
    role_id = Column(Text, nullable=True)
    strategy_version = Column(Text, nullable=True)
    prompt_hash = Column(Text, nullable=True)
    schema_version = Column(Text, nullable=True)

    depends_on_keys = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    input_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    output_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    checkpoint_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    status = Column(
        Enum(
            "pending",
            "queued",
            "running",
            "success",
            "failed",
            "skipped",
            "cancelled",
            name="workflow_step_status_enum",
        ),
        nullable=False,
        server_default="pending",
    )

    attempt_count = Column(Integer, nullable=False, server_default=text("0"))
    error_code = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    last_progress_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
