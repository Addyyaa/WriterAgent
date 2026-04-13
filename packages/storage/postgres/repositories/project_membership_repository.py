from __future__ import annotations

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.project_membership import ProjectMembership


_ROLE_RANK = {
    "viewer": 10,
    "editor": 20,
    "owner": 30,
}


class ProjectMembershipRepository(BaseRepository):
    def get(self, *, project_id, user_id) -> ProjectMembership | None:
        stmt = select(ProjectMembership).where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user_id,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_by_project(self, *, project_id, include_disabled: bool = False) -> list[ProjectMembership]:
        stmt = select(ProjectMembership).where(ProjectMembership.project_id == project_id)
        if not include_disabled:
            stmt = stmt.where(ProjectMembership.status == "active")
        stmt = stmt.order_by(ProjectMembership.created_at.asc())
        return list(self.db.execute(stmt).scalars().all())

    def list_by_user(self, *, user_id, include_disabled: bool = False) -> list[ProjectMembership]:
        stmt = select(ProjectMembership).where(ProjectMembership.user_id == user_id)
        if not include_disabled:
            stmt = stmt.where(ProjectMembership.status == "active")
        stmt = stmt.order_by(ProjectMembership.created_at.desc())
        return list(self.db.execute(stmt).scalars().all())

    def create_or_update(
        self,
        *,
        project_id,
        user_id,
        role: str,
        status: str = "active",
        invited_by=None,
        note: str | None = None,
        auto_commit: bool = True,
    ) -> ProjectMembership:
        row = self.get(project_id=project_id, user_id=user_id)
        if row is None:
            row = ProjectMembership(
                project_id=project_id,
                user_id=user_id,
                role=role,
                status=status,
                invited_by=invited_by,
                note=note,
            )
            self.db.add(row)
        else:
            row.role = role
            row.status = status
            row.invited_by = invited_by
            row.note = note
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def remove(self, *, project_id, user_id, auto_commit: bool = True) -> bool:
        row = self.get(project_id=project_id, user_id=user_id)
        if row is None:
            return False
        self.db.delete(row)
        if auto_commit:
            self.db.commit()
        else:
            self.db.flush()
        return True

    def has_role(self, *, project_id, user_id, min_role: str = "viewer") -> bool:
        row = self.get(project_id=project_id, user_id=user_id)
        if row is None:
            return False
        if str(row.status) != "active":
            return False
        current_rank = _ROLE_RANK.get(str(row.role), 0)
        required_rank = _ROLE_RANK.get(min_role, 10)
        return current_rank >= required_rank

    def backfill_owner_memberships(self, *, auto_commit: bool = True) -> int:
        from packages.storage.postgres.models.project import Project

        stmt = select(Project).where(Project.owner_user_id.is_not(None))
        projects = list(self.db.execute(stmt).scalars().all())
        changed = 0
        for project in projects:
            existing = self.get(project_id=project.id, user_id=project.owner_user_id)
            if existing is None:
                self.db.add(
                    ProjectMembership(
                        project_id=project.id,
                        user_id=project.owner_user_id,
                        role="owner",
                        status="active",
                    )
                )
                changed += 1
            elif str(existing.role) != "owner" or str(existing.status) != "active":
                existing.role = "owner"
                existing.status = "active"
                changed += 1
        if changed:
            if auto_commit:
                self.db.commit()
            else:
                self.db.flush()
        return changed
