from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.chapter_candidate import ChapterCandidate


class ChapterCandidateRepository(BaseRepository):
    def create_candidate(
        self,
        *,
        project_id,
        workflow_run_id,
        workflow_step_id,
        agent_run_id,
        chapter_no: int,
        title: str | None,
        content: str,
        summary: str | None,
        expires_at,
        idempotency_key: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        metadata_json: dict | None = None,
        auto_commit: bool = True,
    ) -> ChapterCandidate:
        if idempotency_key:
            existing = self.get_by_idempotency(idempotency_key)
            if existing is not None:
                return existing
        row = ChapterCandidate(
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            workflow_step_id=workflow_step_id,
            agent_run_id=agent_run_id,
            chapter_no=int(chapter_no),
            title=title,
            content=content,
            summary=summary,
            expires_at=expires_at,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            request_id=request_id,
            metadata_json=metadata_json or {},
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def get(self, candidate_id) -> ChapterCandidate | None:
        return self.db.get(ChapterCandidate, candidate_id)

    def get_by_idempotency(self, key: str) -> ChapterCandidate | None:
        stmt = select(ChapterCandidate).where(ChapterCandidate.idempotency_key == key)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_by_project(
        self,
        *,
        project_id,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ChapterCandidate]:
        stmt = select(ChapterCandidate).where(ChapterCandidate.project_id == project_id)
        if status is not None:
            stmt = stmt.where(ChapterCandidate.status == status)
        stmt = stmt.order_by(ChapterCandidate.created_at.desc()).limit(max(1, int(limit)))
        return list(self.db.execute(stmt).scalars().all())

    def list_by_run(self, *, workflow_run_id) -> list[ChapterCandidate]:
        stmt = (
            select(ChapterCandidate)
            .where(ChapterCandidate.workflow_run_id == workflow_run_id)
            .order_by(ChapterCandidate.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def approve(
        self,
        candidate_id,
        *,
        approved_by,
        approved_chapter_id,
        approved_version_id,
        memory_chunks_count: int,
        auto_commit: bool = True,
    ) -> ChapterCandidate | None:
        row = self.get(candidate_id)
        if row is None:
            return None
        row.status = "approved"
        row.approved_by = approved_by
        row.approved_at = datetime.now(tz=timezone.utc)
        row.approved_chapter_id = approved_chapter_id
        row.approved_version_id = approved_version_id
        row.memory_chunks_count = int(memory_chunks_count)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def reject(self, candidate_id, *, rejected_by, auto_commit: bool = True) -> ChapterCandidate | None:
        row = self.get(candidate_id)
        if row is None:
            return None
        row.status = "rejected"
        row.rejected_by = rejected_by
        row.rejected_at = datetime.now(tz=timezone.utc)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def expire_pending(self, *, now=None, auto_commit: bool = True) -> int:
        now_dt = now or datetime.now(tz=timezone.utc)
        stmt = select(ChapterCandidate).where(
            ChapterCandidate.status == "pending",
            ChapterCandidate.expires_at.is_not(None),
            ChapterCandidate.expires_at <= now_dt,
        )
        rows = list(self.db.execute(stmt).scalars().all())
        for row in rows:
            row.status = "expired"
        if rows:
            if auto_commit:
                self.db.commit()
            else:
                self.db.flush()
        return len(rows)
