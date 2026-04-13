"""
技能运行（SkillRun）的 PostgreSQL ORM 模型（工程级版本）。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Text, func, text, Enum, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class SkillRun(Base):
    __tablename__ = "skill_runs"

    __table_args__ = (
        Index("idx_skillruns_trace", "trace_id"),
        Index("idx_skillruns_agent_run", "agent_run_id"),
        Index("idx_skillruns_status", "status"),
        Index("idx_skillruns_role", "role_id"),
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
    # 技能信息
    # ========================
    skill_name = Column(Text, nullable=True)
    skill_version = Column(Text, nullable=True)
    role_id = Column(Text, nullable=True)
    strategy_version = Column(Text, nullable=True)
    prompt_hash = Column(Text, nullable=True)
    schema_version = Column(Text, nullable=True)

    # ========================
    # 入参/出参快照
    # ========================
    input_snapshot_json = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    output_snapshot_json = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    # ========================
    # 状态
    # ========================
    status = Column(
        Enum("pending", "running", "success", "failed", name="skillrun_status_enum"),
        nullable=False,
        server_default="pending",
    )

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
