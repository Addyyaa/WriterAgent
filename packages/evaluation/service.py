from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from packages.schemas.registry import SchemaRegistry
from packages.storage.postgres.repositories.evaluation_repository import (
    EvaluationDailySnapshot,
    EvaluationRepository,
)


class OnlineEvaluationService:
    """在线评测闭环服务（writing + retrieval）。"""

    def __init__(
        self,
        *,
        repo: EvaluationRepository,
        schema_registry: SchemaRegistry | None = None,
        schema_strict: bool = True,
        schema_degrade_mode: bool = False,
    ) -> None:
        self.repo = repo
        self.schema_registry = schema_registry
        self.schema_strict = bool(schema_strict)
        self.schema_degrade_mode = bool(schema_degrade_mode)

    def validate_feedback_payload(self, payload_json: dict[str, Any]) -> list[str]:
        if self.schema_registry is None:
            return []
        return self.schema_registry.validate(
            schema_ref="api/evaluation_feedback.schema.json",
            payload=payload_json,
            strict=self.schema_strict,
            degrade_mode=self.schema_degrade_mode,
        )

    def start_writing_run(
        self,
        *,
        project_id,
        workflow_run_id,
        request_id: str | None,
        context_json: dict[str, Any] | None = None,
    ):
        return self.repo.create_run(
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            request_id=request_id,
            evaluation_type="writing",
            context_json=context_json or {},
        )

    def record_writing_step(
        self,
        *,
        evaluation_run_id,
        project_id,
        workflow_run_id,
        step_key: str,
        success: bool,
        latency_ms: int | None = None,
        payload_json: dict[str, Any] | None = None,
    ) -> None:
        metric = 1.0 if success else 0.0
        event_payload = dict(payload_json or {})
        event_payload["step_key"] = step_key
        if latency_ms is not None:
            event_payload["latency_ms"] = int(latency_ms)

        self.repo.append_event(
            evaluation_run_id=evaluation_run_id,
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            event_type="writing_step",
            metric_key=f"step.{step_key}.success_rate",
            metric_value=metric,
            payload_json=event_payload,
        )

    def complete_writing_run(
        self,
        *,
        evaluation_run_id,
        project_id,
        workflow_run_id,
        score_breakdown: dict[str, float],
        context_json: dict[str, Any] | None = None,
    ) -> None:
        normalized = {k: float(v) for k, v in dict(score_breakdown or {}).items()}
        total = (sum(normalized.values()) / len(normalized)) if normalized else None

        self.repo.succeed_run(
            evaluation_run_id,
            total_score=total,
            score_breakdown_json=normalized,
            context_json=context_json or {},
        )
        self.repo.append_event(
            evaluation_run_id=evaluation_run_id,
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            event_type="run_completed",
            metric_key="writing.total_score",
            metric_value=total,
            payload_json={"score_breakdown": normalized},
        )

        today = datetime.now(tz=timezone.utc).date()
        for key, value in normalized.items():
            self.repo.upsert_daily_metric(
                project_id=project_id,
                metric_date=today,
                evaluation_type="writing",
                metric_key=f"writing.{key}",
                metric_value=float(value),
                metadata_json={"workflow_run_id": str(workflow_run_id)},
            )
        if total is not None:
            self.repo.upsert_daily_metric(
                project_id=project_id,
                metric_date=today,
                evaluation_type="writing",
                metric_key="writing.total_score",
                metric_value=float(total),
                metadata_json={"workflow_run_id": str(workflow_run_id)},
            )

    def fail_writing_run(
        self,
        *,
        evaluation_run_id,
        error_message: str,
        context_json: dict[str, Any] | None = None,
    ) -> None:
        self.repo.fail_run(
            evaluation_run_id,
            error_message=error_message,
            context_json=context_json or {},
        )

    def record_retrieval_impression(
        self,
        *,
        project_id,
        request_id: str,
        payload_json: dict[str, Any],
        metric_value: float | None = None,
    ) -> None:
        run = self.repo.get_or_create_retrieval_run(
            project_id=project_id,
            request_id=request_id,
            context_json={"source": "memory_search"},
        )
        self.repo.append_event(
            evaluation_run_id=run.id,
            project_id=project_id,
            workflow_run_id=None,
            event_type="retrieval_impression",
            metric_key="retrieval.impression",
            metric_value=metric_value,
            payload_json=payload_json,
        )

        today = datetime.now(tz=timezone.utc).date()
        self.repo.upsert_daily_metric(
            project_id=project_id,
            metric_date=today,
            evaluation_type="retrieval",
            metric_key="retrieval.impression",
            metric_value=1.0,
            metadata_json={"request_id": request_id},
        )

    def record_retrieval_feedback(
        self,
        *,
        project_id,
        request_id: str,
        clicked: bool,
        payload_json: dict[str, Any] | None = None,
    ) -> None:
        run = self.repo.get_or_create_retrieval_run(
            project_id=project_id,
            request_id=request_id,
            context_json={"source": "feedback"},
        )

        score = 1.0 if clicked else 0.0
        self.repo.append_event(
            evaluation_run_id=run.id,
            project_id=project_id,
            workflow_run_id=None,
            event_type="retrieval_feedback",
            metric_key="retrieval.click_rate",
            metric_value=score,
            payload_json=payload_json or {"clicked": bool(clicked)},
        )

        today = datetime.now(tz=timezone.utc).date()
        self.repo.upsert_daily_metric(
            project_id=project_id,
            metric_date=today,
            evaluation_type="retrieval",
            metric_key="retrieval.click_rate",
            metric_value=score,
            metadata_json={"request_id": request_id},
        )

    def record_writing_feedback(
        self,
        *,
        project_id,
        workflow_run_id,
        score: float,
        payload_json: dict[str, Any] | None = None,
    ) -> bool:
        run = self.repo.get_latest_writing_run_by_workflow(workflow_run_id=workflow_run_id)
        if run is None:
            return False

        normalized = max(0.0, min(float(score), 1.0))
        self.repo.append_event(
            evaluation_run_id=run.id,
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            event_type="writing_feedback",
            metric_key="writing.user_score",
            metric_value=normalized,
            payload_json=payload_json or {},
        )
        today = datetime.now(tz=timezone.utc).date()
        self.repo.upsert_daily_metric(
            project_id=project_id,
            metric_date=today,
            evaluation_type="writing",
            metric_key="writing.user_score",
            metric_value=normalized,
            metadata_json={"workflow_run_id": str(workflow_run_id)},
        )
        return True

    def get_run_detail(self, run_id) -> dict[str, Any] | None:
        row = self.repo.get_run(run_id)
        if row is None:
            return None

        events = self.repo.list_events(evaluation_run_id=row.id, limit=500)
        return {
            "id": str(row.id),
            "project_id": str(row.project_id),
            "workflow_run_id": str(row.workflow_run_id) if row.workflow_run_id is not None else None,
            "request_id": row.request_id,
            "evaluation_type": str(row.evaluation_type),
            "status": str(row.status),
            "total_score": float(row.total_score) if row.total_score is not None else None,
            "score_breakdown_json": dict(row.score_breakdown_json or {}),
            "context_json": dict(row.context_json or {}),
            "error_message": row.error_message,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "events": [
                {
                    "id": int(item.id),
                    "event_type": item.event_type,
                    "metric_key": item.metric_key,
                    "metric_value": float(item.metric_value) if item.metric_value is not None else None,
                    "payload_json": dict(item.payload_json or {}),
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
                for item in events
            ],
        }

    def list_daily(
        self,
        *,
        project_id,
        evaluation_type: str | None = None,
        days: int = 30,
    ) -> list[EvaluationDailySnapshot]:
        return self.repo.list_daily(
            project_id=project_id,
            evaluation_type=evaluation_type,
            days=days,
        )
