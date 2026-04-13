from __future__ import annotations

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.consistency_report import ConsistencyReport


class ConsistencyReportRepository(BaseRepository):
    def create_report(
        self,
        *,
        project_id,
        chapter_id=None,
        chapter_version_id=None,
        status: str = "warning",
        score: float | None = None,
        summary: str | None = None,
        issues_json: list[dict] | None = None,
        recommendations_json: list[dict] | None = None,
        source_agent: str | None = None,
        source_workflow: str | None = None,
        trace_id: str | None = None,
        auto_commit: bool = True,
    ) -> ConsistencyReport:
        row = ConsistencyReport(
            project_id=project_id,
            chapter_id=chapter_id,
            chapter_version_id=chapter_version_id,
            status=status,
            score=score,
            summary=summary,
            issues_json=list(issues_json or []),
            recommendations_json=list(recommendations_json or []),
            source_agent=source_agent,
            source_workflow=source_workflow,
            trace_id=trace_id,
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def get(self, report_id) -> ConsistencyReport | None:
        return self.db.get(ConsistencyReport, report_id)

    def list_by_project(self, *, project_id, limit: int = 100) -> list[ConsistencyReport]:
        stmt = (
            select(ConsistencyReport)
            .where(ConsistencyReport.project_id == project_id)
            .order_by(ConsistencyReport.created_at.desc())
            .limit(max(1, int(limit)))
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_latest_by_chapter(self, *, chapter_id) -> ConsistencyReport | None:
        stmt = (
            select(ConsistencyReport)
            .where(ConsistencyReport.chapter_id == chapter_id)
            .order_by(ConsistencyReport.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()
