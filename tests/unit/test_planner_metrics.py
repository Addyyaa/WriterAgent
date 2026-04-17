"""planner 进程内指标汇总逻辑单元测试。"""

from __future__ import annotations

from packages.observability.metrics import InMemoryMetrics
from packages.observability.planner_metrics import bind_planner_metrics, record_planner_event, summarize_planner_counters


def test_record_and_summarize_planner_events() -> None:
    reg = InMemoryMetrics()
    bind_planner_metrics(reg)
    record_planner_event("strict_ok", workflow_type="writing_full")
    record_planner_event("strict_ok", workflow_type="writing_full")
    record_planner_event("strict_schema_failed", workflow_type="chapter_generation")
    counters, _hist = reg.snapshot()
    summary = summarize_planner_counters(counters)
    assert summary["by_event"] == {
        "strict_ok": 2.0,
        "strict_schema_failed": 1.0,
    }
    assert summary["by_workflow_event"]["writing_full:strict_ok"] == 2.0
    assert summary["by_workflow_event"]["chapter_generation:strict_schema_failed"] == 1.0


def test_record_noop_when_registry_unbound() -> None:
    bind_planner_metrics(None)
    reg = InMemoryMetrics()
    record_planner_event("strict_ok", workflow_type="writing_full")
    counters, _ = reg.snapshot()
    assert counters == {}
