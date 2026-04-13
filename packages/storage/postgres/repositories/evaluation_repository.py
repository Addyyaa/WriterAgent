from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.evaluation_daily_metric import EvaluationDailyMetric
from packages.storage.postgres.models.evaluation_event import EvaluationEvent
from packages.storage.postgres.models.evaluation_run import EvaluationRun


@dataclass(frozen=True)
class EvaluationDailySnapshot:
    project_id: str
    metric_date: str
    evaluation_type: str
    metric_key: str
    metric_value: float
    samples: int


class EvaluationRepository(BaseRepository):
    """统一评测仓储：run/event/daily 聚合。"""

    def create_run(
        self,
        *,
        project_id,
        evaluation_type: str,
        workflow_run_id=None,
        request_id: str | None = None,
        context_json: dict | None = None,
        auto_commit: bool = True,
    ) -> EvaluationRun:
        row = EvaluationRun(
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            request_id=request_id,
            evaluation_type=str(evaluation_type),
            status="running",
            context_json=context_json or {},
            score_breakdown_json={},
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def get_run(self, run_id) -> EvaluationRun | None:
        return self.db.get(EvaluationRun, run_id)

    def get_latest_writing_run_by_workflow(self, *, workflow_run_id) -> EvaluationRun | None:
        stmt = (
            select(EvaluationRun)
            .where(
                EvaluationRun.workflow_run_id == workflow_run_id,
                EvaluationRun.evaluation_type == "writing",
            )
            .order_by(EvaluationRun.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_or_create_retrieval_run(
        self,
        *,
        project_id,
        request_id: str,
        context_json: dict | None = None,
    ) -> EvaluationRun:
        stmt = (
            select(EvaluationRun)
            .where(
                EvaluationRun.project_id == project_id,
                EvaluationRun.request_id == request_id,
                EvaluationRun.evaluation_type == "retrieval",
            )
            .order_by(EvaluationRun.created_at.desc())
            .limit(1)
        )
        row = self.db.execute(stmt).scalar_one_or_none()
        if row is not None:
            if context_json:
                merged = dict(row.context_json or {})
                merged.update(context_json)
                row.context_json = merged
                self.db.commit()
                self.db.refresh(row)
            return row

        return self.create_run(
            project_id=project_id,
            evaluation_type="retrieval",
            request_id=request_id,
            context_json=context_json or {},
        )

    def succeed_run(
        self,
        run_id,
        *,
        total_score: float | None,
        score_breakdown_json: dict | None = None,
        context_json: dict | None = None,
        auto_commit: bool = True,
    ) -> EvaluationRun | None:
        row = self.get_run(run_id)
        if row is None:
            return None
        row.status = "success"
        row.total_score = None if total_score is None else float(total_score)
        if score_breakdown_json is not None:
            row.score_breakdown_json = dict(score_breakdown_json)
        if context_json is not None:
            merged = dict(row.context_json or {})
            merged.update(context_json)
            row.context_json = merged
        row.error_message = None
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def fail_run(
        self,
        run_id,
        *,
        error_message: str,
        context_json: dict | None = None,
        auto_commit: bool = True,
    ) -> EvaluationRun | None:
        row = self.get_run(run_id)
        if row is None:
            return None
        row.status = "failed"
        row.error_message = str(error_message)
        if context_json is not None:
            merged = dict(row.context_json or {})
            merged.update(context_json)
            row.context_json = merged
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def append_event(
        self,
        *,
        evaluation_run_id,
        project_id,
        event_type: str,
        workflow_run_id=None,
        metric_key: str | None = None,
        metric_value: float | None = None,
        payload_json: dict | None = None,
        auto_commit: bool = True,
    ) -> EvaluationEvent:
        row = EvaluationEvent(
            evaluation_run_id=evaluation_run_id,
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            event_type=event_type,
            metric_key=metric_key,
            metric_value=None if metric_value is None else float(metric_value),
            payload_json=payload_json or {},
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def list_events(self, *, evaluation_run_id, limit: int = 300) -> list[EvaluationEvent]:
        stmt = (
            select(EvaluationEvent)
            .where(EvaluationEvent.evaluation_run_id == evaluation_run_id)
            .order_by(EvaluationEvent.created_at.asc(), EvaluationEvent.id.asc())
            .limit(max(1, int(limit)))
        )
        return list(self.db.execute(stmt).scalars().all())

    def upsert_daily_metric(
        self,
        *,
        project_id,
        metric_date: date,
        evaluation_type: str,
        metric_key: str,
        metric_value: float,
        samples_delta: int = 1,
        metadata_json: dict | None = None,
        auto_commit: bool = True,
    ) -> EvaluationDailyMetric:
        stmt = select(EvaluationDailyMetric).where(
            EvaluationDailyMetric.project_id == project_id,
            EvaluationDailyMetric.metric_date == metric_date,
            EvaluationDailyMetric.evaluation_type == evaluation_type,
            EvaluationDailyMetric.metric_key == metric_key,
        )
        row = self.db.execute(stmt).scalar_one_or_none()
        if row is None:
            row = EvaluationDailyMetric(
                project_id=project_id,
                metric_date=metric_date,
                evaluation_type=evaluation_type,
                metric_key=metric_key,
                metric_value=0.0,
                samples=0,
                metadata_json=metadata_json or {},
            )
            self.db.add(row)
            self.db.flush()

        delta = max(1, int(samples_delta))
        old_samples = int(row.samples or 0)
        new_samples = old_samples + delta
        old_sum = float(row.metric_value or 0.0) * old_samples
        new_sum = float(metric_value) * delta
        row.metric_value = (old_sum + new_sum) / new_samples
        row.samples = new_samples
        if metadata_json:
            merged = dict(row.metadata_json or {})
            merged.update(metadata_json)
            row.metadata_json = merged

        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def list_daily(
        self,
        *,
        project_id,
        evaluation_type: str | None = None,
        days: int = 30,
    ) -> list[EvaluationDailySnapshot]:
        stmt = select(EvaluationDailyMetric).where(EvaluationDailyMetric.project_id == project_id)
        if evaluation_type is not None:
            stmt = stmt.where(EvaluationDailyMetric.evaluation_type == evaluation_type)
        window = max(1, int(days))
        floor = datetime.now(tz=timezone.utc).date() - timedelta(days=window - 1)
        stmt = stmt.where(EvaluationDailyMetric.metric_date >= floor)
        stmt = stmt.order_by(
            EvaluationDailyMetric.metric_date.desc(),
            EvaluationDailyMetric.evaluation_type.asc(),
            EvaluationDailyMetric.metric_key.asc(),
        )

        out: list[EvaluationDailySnapshot] = []
        for row in self.db.execute(stmt).scalars().all():
            out.append(
                EvaluationDailySnapshot(
                    project_id=str(row.project_id),
                    metric_date=row.metric_date.isoformat(),
                    evaluation_type=str(row.evaluation_type),
                    metric_key=str(row.metric_key),
                    metric_value=float(row.metric_value or 0.0),
                    samples=int(row.samples or 0),
                )
            )
        return out
