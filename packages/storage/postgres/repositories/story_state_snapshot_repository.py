from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.story_state_snapshot import StoryStateSnapshot


class StoryStateSnapshotRepository(BaseRepository):
    def get_latest_before(self, *, project_id, before_chapter_no: int) -> StoryStateSnapshot | None:
        """返回 strictly 早于 before_chapter_no 的最新一条快照（续写第 N 章时传 N）。"""
        stmt = (
            select(StoryStateSnapshot)
            .where(
                StoryStateSnapshot.project_id == project_id,
                StoryStateSnapshot.chapter_no < int(before_chapter_no),
            )
            .order_by(StoryStateSnapshot.chapter_no.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def upsert_for_chapter(
        self,
        *,
        project_id,
        chapter_no: int,
        state_json: dict,
        source: str = "candidate_approve",
        auto_commit: bool = True,
    ) -> StoryStateSnapshot:
        now = datetime.now(tz=timezone.utc)
        stmt = select(StoryStateSnapshot).where(
            StoryStateSnapshot.project_id == project_id,
            StoryStateSnapshot.chapter_no == int(chapter_no),
        )
        row = self.db.execute(stmt).scalar_one_or_none()
        if row is None:
            row = StoryStateSnapshot(
                project_id=project_id,
                chapter_no=int(chapter_no),
                state_json=dict(state_json or {}),
                source=str(source or "")[:64] or "candidate_approve",
            )
            self.db.add(row)
        else:
            row.state_json = dict(state_json or {})
            row.source = str(source or "")[:64] or "candidate_approve"
            row.updated_at = now
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row
