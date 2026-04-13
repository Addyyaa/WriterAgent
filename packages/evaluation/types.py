from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvaluationRun:
    run_id: str
    project_id: str
    evaluation_type: str
    status: str
    total_score: float | None
    score_breakdown: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationEvent:
    event_type: str
    metric_key: str | None
    metric_value: float | None
    payload_json: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None


@dataclass(frozen=True)
class EvaluationDailyMetric:
    metric_date: str
    evaluation_type: str
    metric_key: str
    metric_value: float
    samples: int
