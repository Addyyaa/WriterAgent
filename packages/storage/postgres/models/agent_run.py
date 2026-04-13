"""
Agent 运行记录（AgentRun）的 PostgreSQL ORM 模型（工程级版本）。

用于审计、排障、性能分析与可观测性系统。
"""

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    Text,
    func,
    text,
    Enum,
    Index,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    __table_args__ = (
        # 🔥 核心查询索引
        Index("idx_agent_trace", "trace_id"),
        Index("idx_agent_project", "project_id"),
        Index("idx_agent_status", "status"),
        Index("idx_agent_role", "role_id"),

        # 🔥 调试查询（按请求查）
        Index("idx_agent_request", "request_id"),

        # 🔥 JSON查询优化（可选但推荐）
        Index("idx_agent_input_json", "input_json", postgresql_using="gin"),
        Index("idx_agent_output_json", "output_json", postgresql_using="gin"),
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    # ========================
    # Trace / 请求标识
    # ========================

    trace_id = Column(Text, nullable=True)
    request_id = Column(Text, nullable=True)

    # ========================
    # 业务上下文
    # ========================

    project_id = Column(UUID(as_uuid=True), nullable=True)

    agent_name = Column(Text, nullable=True)
    task_type = Column(Text, nullable=True)
    role_id = Column(Text, nullable=True)
    strategy_version = Column(Text, nullable=True)
    prompt_hash = Column(Text, nullable=True)
    schema_version = Column(Text, nullable=True)

    # ========================
    # 输入输出快照
    # ========================

    input_json = Column(JSONB, nullable=True)
    output_json = Column(JSONB, nullable=True)

    # ========================
    # 状态（必须用 Enum）
    # ========================

    status = Column(
        Enum(
            "pending",
            "running",
            "success",
            "failed",
            name="agent_run_status_enum",
        ),
        nullable=False,
        server_default="pending",
    )

    error_code = Column(Text, nullable=True)

    # ========================
    # 执行信息
    # ========================

    retry_count = Column(
        Integer,
        nullable=False,
        server_default=text("0"),  # 🔥 修复（不能默认2）
    )

    latency_ms = Column(Integer, nullable=True)

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
