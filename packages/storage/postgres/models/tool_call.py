"""
工具调用（ToolCall）的 PostgreSQL ORM 模型（工程级版本）。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text, func, text, Enum, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class ToolCall(Base):
    __tablename__ = "tool_calls"

    __table_args__ = (
        Index("idx_toolcalls_trace", "trace_id"),
        Index("idx_toolcalls_agent_run", "agent_run_id"),
        Index("idx_toolcalls_status", "status"),
        Index("idx_toolcalls_role", "role_id"),
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
    # 追踪信息
    # ========================
    trace_id = Column(Text, nullable=True)
    agent_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ========================
    # 工具信息
    # ========================
    tool_name = Column(Text, nullable=True)
    role_id = Column(Text, nullable=True)
    strategy_version = Column(Text, nullable=True)
    prompt_hash = Column(Text, nullable=True)
    schema_version = Column(Text, nullable=True)

    # ========================
    # JSONB 入参/出参
    # ========================
    input_json = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    output_json = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    # ========================
    # 状态
    # ========================
    status = Column(
        Enum("pending", "running", "success", "failed", name="toolcall_status_enum"),
        nullable=False,
        server_default="pending",
    )
    error_code = Column(Text, nullable=True)
    latency_ms = Column(Integer, nullable=True)

    # ========================
    # 时间字段
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
