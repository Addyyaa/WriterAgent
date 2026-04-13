from __future__ import annotations

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.timeline_event import TimelineEvent


class TimelineEventRepository(BaseRepository):
    def create(
        self,
        *,
        project_id,
        chapter_no: int | None = None,
        event_title: str | None = None,
        event_desc: str | None = None,
        location: str | None = None,
        involved_characters: list[str] | None = None,
        causal_links: list[dict] | None = None,
        auto_commit: bool = True,
    ) -> TimelineEvent:
        row = TimelineEvent(
            project_id=project_id,
            chapter_no=chapter_no,
            event_title=event_title,
            event_desc=event_desc,
            location=location,
            involved_characters=list(involved_characters or []),
            causal_links=list(causal_links or []),
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def get(self, event_id) -> TimelineEvent | None:
        return self.db.get(TimelineEvent, event_id)

    def list_by_project(
        self,
        *,
        project_id,
        limit: int = 300,
        chapter_no: int | None = None,
    ) -> list[TimelineEvent]:
        stmt = select(TimelineEvent).where(TimelineEvent.project_id == project_id)
        if chapter_no is not None:
            stmt = stmt.where(TimelineEvent.chapter_no == int(chapter_no))
        stmt = stmt.order_by(TimelineEvent.created_at.desc()).limit(max(1, int(limit)))
        return list(self.db.execute(stmt).scalars().all())

    def update(self, event_id, *, auto_commit: bool = True, **fields) -> TimelineEvent | None:
        row = self.get(event_id)
        if row is None:
            return None
        allowed = {
            "chapter_no",
            "event_title",
            "event_desc",
            "location",
            "involved_characters",
            "causal_links",
        }
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            if key in {"involved_characters", "causal_links"}:
                setattr(row, key, list(value))
            else:
                setattr(row, key, value)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def delete(self, event_id, *, auto_commit: bool = True) -> bool:
        row = self.get(event_id)
        if row is None:
            return False
        self.db.delete(row)
        if auto_commit:
            self.db.commit()
        else:
            self.db.flush()
        return True

