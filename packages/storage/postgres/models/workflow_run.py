from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    Enum,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class WorkflowRun(Base):
    """工作流运行记录。"""

    __tablename__ = "workflow_runs"

    __table_args__ = (
        Index("idx_workflow_runs_project", "project_id"),
        Index("idx_workflow_runs_status", "status"),
        Index("idx_workflow_runs_type", "workflow_type"),
        Index("idx_workflow_runs_queue", "status", "next_attempt_at"),
        Index("idx_workflow_runs_trace", "trace_id"),
        Index("idx_workflow_runs_idempotency", "idempotency_key", unique=True),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    initiated_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    parent_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    trace_id = Column(Text, nullable=True)
    request_id = Column(Text, nullable=True)
    idempotency_key = Column(Text, nullable=True)

    workflow_type = Column(Text, nullable=False)
    status = Column(
        Enum(
            "queued",
            "running",
            "waiting_review",
            "success",
            "failed",
            "cancelled",
            name="workflow_run_status_enum",
        ),
        nullable=False,
        server_default="queued",
    )

    priority = Column(Integer, nullable=False, server_default=text("100"))
    retry_count = Column(Integer, nullable=False, server_default=text("0"))
    max_retries = Column(Integer, nullable=False, server_default=text("2"))

    input_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    plan_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    output_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    error_code = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
