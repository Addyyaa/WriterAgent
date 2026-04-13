"""
规范记忆事实（MemoryFact）ORM 模型。

该表用于存储去重后的规范事实（canonical fact）：
1. 一条事实只保留一份 embedding（用于检索）。
2. 通过 ``canonical_hash`` 做精确去重。
3. 通过语义相似匹配做近似去重。
"""

from sqlalchemy import (
    Column,
    DateTime,
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
from ..types import PgVector
from ..vector_settings import MEMORY_EMBEDDING_DIM


class MemoryFact(Base):
    __tablename__ = "memory_facts"

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "canonical_hash",
            name="uq_memory_facts_project_hash",
        ),
        Index(
            "idx_memory_facts_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("idx_memory_facts_project", "project_id"),
        Index("idx_memory_facts_last_seen", "last_seen_at"),
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

    canonical_text = Column(Text, nullable=False)
    summary_text = Column(Text, nullable=True)
    canonical_hash = Column(Text, nullable=False)
    embedding = Column(PgVector(MEMORY_EMBEDDING_DIM), nullable=False)

    metadata_json = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    mention_count = Column(Integer, nullable=False, server_default=text("1"))
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
