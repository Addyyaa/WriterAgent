from __future__ import annotations

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.world_entry import WorldEntry


class WorldEntryRepository(BaseRepository):
    def create(
        self,
        *,
        project_id,
        entry_type: str | None = None,
        title: str | None = None,
        content: str | None = None,
        metadata_json: dict | None = None,
        is_canonical: bool = True,
        auto_commit: bool = True,
    ) -> WorldEntry:
        row = WorldEntry(
            project_id=project_id,
            entry_type=entry_type,
            title=title,
            content=content,
            metadata_json=dict(metadata_json or {}),
            is_canonical=bool(is_canonical),
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def get(self, entry_id) -> WorldEntry | None:
        return self.db.get(WorldEntry, entry_id)

    def list_by_project(
        self,
        *,
        project_id,
        limit: int = 200,
        canonical_only: bool = False,
    ) -> list[WorldEntry]:
        stmt = select(WorldEntry).where(WorldEntry.project_id == project_id)
        if canonical_only:
            stmt = stmt.where(WorldEntry.is_canonical.is_(True))
        stmt = stmt.order_by(WorldEntry.updated_at.desc()).limit(max(1, int(limit)))
        return list(self.db.execute(stmt).scalars().all())

    def update(self, entry_id, *, auto_commit: bool = True, **fields) -> WorldEntry | None:
        row = self.get(entry_id)
        if row is None:
            return None
        allowed = {
            "entry_type",
            "title",
            "content",
            "metadata_json",
            "is_canonical",
            "version",
        }
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            if key == "metadata_json":
                setattr(row, key, dict(value))
            elif key == "is_canonical":
                setattr(row, key, bool(value))
            else:
                setattr(row, key, value)

        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def delete(self, entry_id, *, auto_commit: bool = True) -> bool:
        row = self.get(entry_id)
        if row is None:
            return False
        self.db.delete(row)
        if auto_commit:
            self.db.commit()
        else:
            self.db.flush()
        return True

