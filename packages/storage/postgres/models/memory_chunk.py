"""
记忆分块（MemoryChunk）的 PostgreSQL ORM 模型。

定义 ``memory_chunks`` 表的对象映射，用于按项目存储检索/向量管线中的文本块、
来源引用、1024 维嵌入向量及 IVFFlat（余弦）索引。
"""

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base
from ..types import PgVector
from ..vector_settings import MEMORY_EMBEDDING_DIM


class MemoryChunk(Base):
    """
    单条记忆分块实体，对应数据库表 ``memory_chunks``。

    作为 RAG 系统的核心存储模型，该表用于持久化文本分块、来源溯源、向量嵌入及扩展元数据，
    支持按项目隔离、按来源追溯、按类型检索、按向量相似度查询，是知识库检索与上下文生成的基础。

    设计遵循多源接入、分块治理、向量检索、状态可追踪的工程化理念，
    支持灵活扩展各类数据源、分块策略与业务元数据，确保系统可扩展、可维护、可观测。

    Attributes:
        id: 分块唯一标识，UUID 主键，由数据库自动生成，确保全局唯一性。
        project_id: 所属项目 ID，外键关联 projects 表，项目删除时自动级联清除所有分块。
        source_type: 数据源类型（如文档、章节、词条、对话），用于标识分块的原始业务来源。
        source_id: 数据源实体唯一 ID，与 source_type 配合实现业务溯源，不建立物理外键以保持多源兼容。
        chunk_type: 分块内容类型（如正文、摘要、标题、关键词、规则），用于差异化检索与生成策略。
        chunk_text: 分块原始文本内容，数据库列名为 text，ORM 层使用别名避免关键字冲突。
        summary_text: 分块摘要文本（可选），用于上下文预算受限时的高密度提示与召回增强。
        metadata_json: 灵活扩展的 JSONB 元数据，用于存储业务扩展信息，支持索引与快速查询。
            时间语义约定：
            - source_timestamp: ISO8601 datetime | null，表示“内容语义发生时间”
              （而非写库时间 created_at/ingested_at）。
            该字段用于时间排序检索、最近事件查询、剧情演化上下文构建及冲突信息优先级判断。
        embedding_status: 向量生成状态。当前库内枚举为：
            pending/queued/processing/retrying/done/failed/stale。
            业务建议的完整状态设计如下（便于后续扩展任务队列与重算）：
            - pending: 分块已入库，尚未进入任务队列。
            - queued: 已入队等待执行。
            - processing: worker 已领取任务，正在生成向量。
            - done: 向量已生成并落库，可参与检索。
            - retrying: 失败后进入重试流程。
            - failed: 最终失败或不可恢复错误。
            - stale: 向量因文本改稿/模型升级而过期。
            推荐流转：pending -> queued -> processing -> done；异常链路可进入
            retrying/failed；done 在内容变更时可转 stale 再重算。
        embedding: 1024 维向量表示，由嵌入模型生成，用于 pgvector 余弦相似度检索。
        created_at: 记录创建时间，带时区，用于数据排序与生命周期管理。
        updated_at: 记录最后更新时间，带时区，自动刷新，用于数据变更追踪。
"""

    __tablename__ = "memory_chunks"

    __table_args__ = (
        # 向量索引：使用 pgvector ivfflat 索引加速近似最近邻检索。
        # 原理：先将向量聚类成多个列表（lists），查询时优先在最相关簇内搜索，
        # 避免全表逐行距离计算，从而显著降低大规模检索成本。
        Index(
            "idx_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # 核心查询索引
        Index("idx_chunks_project", "project_id"),
        Index("idx_chunks_source", "source_type", "source_id"),
        # JSON索引
        Index("idx_chunks_metadata", "metadata_json", postgresql_using="gin"),
        # 关键词检索索引：支撑 PostgreSQL FTS 的 to_tsvector 检索。
        Index(
            "idx_chunks_text_tsv",
            text("to_tsvector('simple', coalesce(text, ''))"),
            postgresql_using="gin",
        ),
        Index(
            "idx_chunks_summary_tsv",
            text("to_tsvector('simple', coalesce(summary_text, ''))"),
            postgresql_using="gin",
        ),
        # 语义时间索引（表达式索引）：
        # 基于 metadata_json->>'source_timestamp' 做字符串时序检索/排序。
        # 约定写入 UTC ISO8601（Z 后缀）后，字符串顺序与时间顺序一致。
        Index(
            "idx_chunks_source_timestamp",
            text("((metadata_json ->> 'source_timestamp'))"),
            postgresql_where=text("(metadata_json ? 'source_timestamp')"),
        ),
    )

    # ========================
    # 主键
    # ========================
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    # ========================
    # 项目关联
    # ========================
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ========================
    # 来源与类型
    # ========================
    source_type = Column(Text, nullable=True)
    source_id = Column(UUID(as_uuid=True), nullable=True)
    chunk_type = Column(Text, nullable=True)
    chunk_text = Column("text", Text, nullable=True)
    summary_text = Column(Text, nullable=True)

    # ========================
    # 扩展字段
    # ========================
    metadata_json = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    # 当前数据库枚举支持完整状态机。
    embedding_status = Column(
        Enum(
            "pending",
            "queued",
            "processing",
            "retrying",
            "done",
            "failed",
            "stale",
            name="embedding_status_enum",
            native_enum=True,
        ),
        nullable=False,
        server_default=text("'pending'"),
    )

    embedding = Column(PgVector(MEMORY_EMBEDDING_DIM), nullable=True)

    # ========================
    # 时间
    # ========================
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
