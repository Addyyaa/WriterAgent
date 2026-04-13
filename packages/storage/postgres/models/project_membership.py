from __future__ import annotations

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Index, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID

from ..base import Base


class ProjectMembership(Base):
    __tablename__ = "project_memberships"

    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_memberships_project_user"),
        Index("idx_project_memberships_project_role", "project_id", "role"),
        Index("idx_project_memberships_user", "user_id"),
        Index("idx_project_memberships_status", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    role = Column(
        Enum("owner", "editor", "viewer", name="project_membership_role_enum"),
        nullable=False,
        server_default="viewer",
    )
    status = Column(
        Enum("active", "invited", "disabled", name="project_membership_status_enum"),
        nullable=False,
        server_default="active",
    )

    invited_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
