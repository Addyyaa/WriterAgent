"""Planner 强/弱知识 schema 路径计数：与 API 进程内 InMemoryMetrics 绑定（Worker 仅日志，可不绑定）。"""

from __future__ import annotations

from packages.observability.metrics import InMemoryMetrics

_bound: InMemoryMetrics | None = None


def bind_planner_metrics(registry: InMemoryMetrics | None) -> None:
    """在 FastAPI 创建 metrics_registry 后调用，使 planner 递增与 API 同源计数。"""
    global _bound
    _bound = registry


def record_planner_event(event: str, *, workflow_type: str = "") -> None:
    """event 建议使用稳定短名：strict_ok, strict_schema_failed, loose_retry_ok, loose_retry_failed, empty_nodes_mock, fallback_mock。"""
    r = _bound
    if r is None:
        return
    wf = str(workflow_type or "unknown").strip()[:128] or "unknown"
    r.inc(
        "writeragent_planner_events_total",
        1.0,
        event=str(event or "unknown")[:64],
        workflow_type=wf,
    )


def summarize_planner_counters(counters: dict) -> dict[str, object]:
    """将 snapshot 中的 writeragent_planner_events_total 按 event 聚合为可读 dict。"""
    by_event: dict[str, float] = {}
    by_workflow: dict[str, float] = {}
    for (name, labels), value in counters.items():
        if str(name) != "writeragent_planner_events_total":
            continue
        label_map = dict(labels or [])
        ev = str(label_map.get("event") or "unknown")
        wf = str(label_map.get("workflow_type") or "unknown")
        by_event[ev] = by_event.get(ev, 0.0) + float(value or 0.0)
        key = f"{wf}:{ev}"
        by_workflow[key] = by_workflow.get(key, 0.0) + float(value or 0.0)
    return {"by_event": by_event, "by_workflow_event": by_workflow}
