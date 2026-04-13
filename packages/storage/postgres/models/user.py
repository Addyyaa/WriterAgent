"""
用户（User）的 PostgreSQL ORM 模型（工程级版本）。
"""

from sqlalchemy import Column, DateTime, Text, func, text, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class User(Base):
    __tablename__ = "users"

    __table_args__ = (
        # 可以在 username/email 查询时提升性能
        Index("idx_users_username", "username"),
        Index("idx_users_email", "email"),
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
    # 登录信息
    # ========================
    username = Column(Text, unique=True, nullable=False)
    email = Column(Text, unique=True, nullable=True)
    password_hash = Column(Text, nullable=True)

    # ========================
    # 用户偏好
    # ========================
    preferences = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
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