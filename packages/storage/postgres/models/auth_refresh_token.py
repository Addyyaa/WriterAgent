from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import UUID

from ..base import Base


class AuthRefreshToken(Base):
    __tablename__ = "auth_refresh_tokens"

    __table_args__ = (
        Index("idx_auth_refresh_tokens_user", "user_id"),
        Index("idx_auth_refresh_tokens_expires", "expires_at"),
        Index("idx_auth_refresh_tokens_revoked", "revoked_at"),
        Index("idx_auth_refresh_tokens_jti", "jti", unique=True),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    jti = Column(Text, nullable=False, unique=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(Text, nullable=False)

    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    ip_hash = Column(Text, nullable=True)
    user_agent = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
