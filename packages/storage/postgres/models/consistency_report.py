from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class ConsistencyReport(Base):
    """一致性审查报告。"""

    __tablename__ = "consistency_reports"

    __table_args__ = (
        Index("idx_consistency_reports_project_created", "project_id", "created_at"),
        Index("idx_consistency_reports_status", "status"),
        Index("idx_consistency_reports_chapter", "chapter_id", "chapter_version_id"),
        Index("idx_consistency_reports_trace", "trace_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    chapter_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chapters.id", ondelete="SET NULL"),
        nullable=True,
    )
    chapter_version_id = Column(BigInteger, ForeignKey("chapter_versions.id", ondelete="SET NULL"), nullable=True)

    status = Column(
        Enum(
            "passed",
            "warning",
            "failed",
            name="consistency_report_status_enum",
        ),
        nullable=False,
        server_default="warning",
    )

    score = Column(Float, nullable=True)
    summary = Column(Text, nullable=True)

    issues_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    recommendations_json = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))

    source_agent = Column(Text, nullable=True)
    source_workflow = Column(Text, nullable=True)
    trace_id = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
