from __future__ import annotations

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..base import Base


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    __table_args__ = (
        Index("idx_webhook_deliveries_status_next", "status", "next_attempt_at"),
        Index("idx_webhook_deliveries_project_created", "project_id", "created_at"),
        Index("idx_webhook_deliveries_subscription", "subscription_id"),
        Index("idx_webhook_deliveries_event", "event_type"),
        Index("idx_webhook_deliveries_event_id", "event_id", unique=True),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    event_id = Column(Text, nullable=False, unique=True)

    subscription_id = Column(UUID(as_uuid=True), ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)

    event_type = Column(Text, nullable=False)
    payload_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    signature = Column(Text, nullable=True)

    status = Column(
        Enum("pending", "retrying", "success", "dead", name="webhook_delivery_status_enum"),
        nullable=False,
        server_default="pending",
    )
    attempt_count = Column(Integer, nullable=False, server_default=text("0"))
    max_attempts = Column(Integer, nullable=False, server_default=text("8"))
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)

    response_status = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    trace_id = Column(Text, nullable=True)
    request_id = Column(Text, nullable=True)

    delivered_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
