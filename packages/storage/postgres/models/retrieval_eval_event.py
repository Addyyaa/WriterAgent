from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class RetrievalEvalEvent(Base):
    """检索在线评测事件（曝光 + 点击回写）。"""

    __tablename__ = "retrieval_eval_events"

    __table_args__ = (
        Index("idx_reval_events_project_created", "project_id", "created_at"),
        Index("idx_reval_events_variant_created", "variant", "created_at"),
        Index("idx_reval_events_request", "request_id", unique=True),
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    request_id = Column(Text, nullable=False)
    user_id = Column(Text, nullable=True)
    query = Column(Text, nullable=False)
    variant = Column(Text, nullable=False)
    rerank_backend = Column(Text, nullable=True)
    impressed_doc_ids = Column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    clicked = Column(Boolean, nullable=False, server_default=text("false"))
    clicked_doc_id = Column(Text, nullable=True)
    context_json = Column(
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

