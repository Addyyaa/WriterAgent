from __future__ import annotations

from sqlalchemy import func, select

from .base import BaseRepository
from packages.storage.postgres.models.outline import Outline


class OutlineRepository(BaseRepository):
    def create_version(
        self,
        *,
        project_id,
        title: str | None,
        content: str | None,
        structure_json: dict | None,
        source_agent: str | None,
        source_workflow: str | None,
        trace_id: str | None,
        set_active: bool = True,
        auto_commit: bool = True,
    ) -> Outline:
        stmt = select(func.max(Outline.version_no)).where(Outline.project_id == project_id)
        max_version = self.db.execute(stmt).scalar()
        next_version = 1 if max_version is None else int(max_version) + 1

        if set_active:
            self.db.query(Outline).filter(Outline.project_id == project_id, Outline.is_active.is_(True)).update(
                {Outline.is_active: False}, synchronize_session=False
            )

        row = Outline(
            project_id=project_id,
            version_no=next_version,
            title=title,
            content=content,
            structure_json=structure_json or {},
            source_agent=source_agent,
            source_workflow=source_workflow,
            trace_id=trace_id,
            is_active=set_active,
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def get(self, outline_id) -> Outline | None:
        return self.db.get(Outline, outline_id)

    def get_latest(self, *, project_id) -> Outline | None:
        stmt = (
            select(Outline)
            .where(Outline.project_id == project_id)
            .order_by(Outline.version_no.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_active(self, *, project_id) -> Outline | None:
        stmt = (
            select(Outline)
            .where(Outline.project_id == project_id, Outline.is_active.is_(True))
            .order_by(Outline.version_no.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_by_project(self, *, project_id, limit: int = 50) -> list[Outline]:
        stmt = (
            select(Outline)
            .where(Outline.project_id == project_id)
            .order_by(Outline.version_no.desc())
            .limit(max(1, int(limit)))
        )
        return list(self.db.execute(stmt).scalars().all())
