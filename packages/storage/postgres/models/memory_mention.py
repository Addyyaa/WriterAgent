"""
原始提及（MemoryMention）ORM 模型。

该表用于记录用户/文档的原始提及（raw mention），并关联到规范事实（MemoryFact）：
1. 保留原文与来源，保证可追溯性。
2. 对重复提及做聚合计数，避免同源重复膨胀。
3. 记录提及归并到事实时的语义距离，便于后续审计与调优。
"""

from sqlalchemy import (
    Column,
    DateTime,
    Float,
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


class MemoryMention(Base):
    __tablename__ = "memory_mentions"

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "fact_id",
            "mention_hash",
            "source_type",
            "source_id",
            "chunk_type",
            name="uq_memory_mentions_dedup",
        ),
        Index("idx_memory_mentions_project", "project_id"),
        Index("idx_memory_mentions_fact", "fact_id"),
        Index("idx_memory_mentions_source", "source_type", "source_id"),
        Index("idx_memory_mentions_last_seen", "last_seen_at"),
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
    fact_id = Column(
        UUID(as_uuid=True),
        ForeignKey("memory_facts.id", ondelete="CASCADE"),
        nullable=False,
    )

    source_type = Column(Text, nullable=False)
    source_id = Column(UUID(as_uuid=True), nullable=True)
    chunk_type = Column(Text, nullable=True)

    raw_text = Column(Text, nullable=False)
    mention_hash = Column(Text, nullable=False)
    distance_to_fact = Column(Float, nullable=True)

    metadata_json = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    occurrence_count = Column(Integer, nullable=False, server_default=text("1"))
    first_seen_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_seen_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
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

