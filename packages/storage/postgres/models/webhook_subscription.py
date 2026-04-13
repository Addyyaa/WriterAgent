from __future__ import annotations

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Index, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "event_type",
            "target_url",
            name="uq_webhook_subscription_project_event_url",
        ),
        Index("idx_webhook_subscriptions_project", "project_id"),
        Index("idx_webhook_subscriptions_status", "status"),
        Index("idx_webhook_subscriptions_event", "event_type"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    event_type = Column(Text, nullable=False)
    target_url = Column(Text, nullable=False)
    secret = Column(Text, nullable=False)

    status = Column(
        Enum("active", "paused", name="webhook_subscription_status_enum"),
        nullable=False,
        server_default="active",
    )
    max_retries = Column(Integer, nullable=False, server_default=text("8"))
    timeout_seconds = Column(Integer, nullable=False, server_default=text("10"))

    headers_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    metadata_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
