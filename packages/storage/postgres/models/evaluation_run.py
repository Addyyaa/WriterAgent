from __future__ import annotations

from sqlalchemy import Column, DateTime, Enum, Float, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class EvaluationRun(Base):
    """统一评测运行（retrieval / writing）。"""

    __tablename__ = "evaluation_runs"

    __table_args__ = (
        Index("idx_eval_runs_project_created", "project_id", "created_at"),
        Index("idx_eval_runs_type_status", "evaluation_type", "status"),
        Index("idx_eval_runs_workflow", "workflow_run_id"),
        Index("idx_eval_runs_request", "request_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    workflow_run_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True)
    request_id = Column(Text, nullable=True)

    evaluation_type = Column(
        Enum("retrieval", "writing", name="evaluation_type_enum"),
        nullable=False,
        server_default=text("'writing'"),
    )
    status = Column(
        Enum("running", "success", "failed", name="evaluation_run_status_enum"),
        nullable=False,
        server_default=text("'running'"),
    )

    total_score = Column(Float, nullable=True)
    score_breakdown_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    context_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
