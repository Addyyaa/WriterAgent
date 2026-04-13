from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


_EVENT_PRIORITY = {
    "run_status_changed": 10,
    "step_started": 20,
    "candidate_waiting_review": 30,
    "step_succeeded": 40,
    "step_failed": 40,
    "candidate_approved": 50,
    "candidate_rejected": 50,
    "run_completed": 60,
}


def build_run_events(detail: dict[str, Any]) -> list[dict[str, Any]]:
    run_id = str(detail.get("id") or "").strip()
    trace_id = str(detail.get("trace_id") or "").strip() or None

    records: list[tuple[datetime, str, dict[str, Any]]] = []

    created_at = _parse_ts(detail.get("created_at"))
    started_at = _parse_ts(detail.get("started_at"))
    updated_at = _parse_ts(detail.get("updated_at"))
    finished_at = _parse_ts(detail.get("finished_at"))
    status = str(detail.get("status") or "").strip()

    if created_at is not None:
        records.append(
            (
                created_at,
                "run_status_changed",
                {"status": "queued", "from_status": None, "to_status": "queued"},
            )
        )
    if started_at is not None:
        records.append(
            (
                started_at,
                "run_status_changed",
                {"status": "running", "from_status": "queued", "to_status": "running"},
            )
        )
    if status == "waiting_review" and updated_at is not None:
        records.append(
            (
                updated_at,
                "run_status_changed",
                {"status": "waiting_review", "from_status": "running", "to_status": "waiting_review"},
            )
        )
    if status in {"success", "failed", "cancelled"} and finished_at is not None:
        records.append(
            (
                finished_at,
                "run_status_changed",
                {"status": status, "from_status": "running", "to_status": status},
            )
        )

    for step in list(detail.get("steps") or []):
        step_id = step.get("id")
        step_key = step.get("step_key")
        step_status = str(step.get("status") or "").strip()
        step_started = _parse_ts(step.get("started_at"))
        step_finished = _parse_ts(step.get("finished_at"))
        payload_base = {
            "step_id": int(step_id) if step_id is not None else None,
            "step_key": step_key,
            "step_type": step.get("step_type"),
            "workflow_type": step.get("workflow_type"),
            "attempt_count": int(step.get("attempt_count") or 0),
            "role_id": step.get("role_id"),
        }
        if step_started is not None:
            records.append((step_started, "step_started", dict(payload_base)))
        if step_finished is not None and step_status == "success":
            records.append((step_finished, "step_succeeded", dict(payload_base)))
        if step_finished is not None and step_status in {"failed", "cancelled", "skipped"}:
            fail_payload = dict(payload_base)
            fail_payload["status"] = step_status
            fail_payload["error_code"] = step.get("error_code")
            fail_payload["error_message"] = step.get("error_message")
            records.append((step_finished, "step_failed", fail_payload))

    for candidate in list(detail.get("candidates") or []):
        candidate_id = candidate.get("id")
        base_payload = {
            "candidate_id": candidate_id,
            "workflow_step_id": candidate.get("workflow_step_id"),
            "chapter_no": candidate.get("chapter_no"),
            "title": candidate.get("title"),
            "status": candidate.get("status"),
        }
        c_created = _parse_ts(candidate.get("created_at"))
        c_approved = _parse_ts(candidate.get("approved_at"))
        c_rejected = _parse_ts(candidate.get("rejected_at"))
        if c_created is not None:
            records.append((c_created, "candidate_waiting_review", dict(base_payload)))
        if c_approved is not None:
            approved_payload = dict(base_payload)
            approved_payload["approved_chapter_id"] = candidate.get("approved_chapter_id")
            approved_payload["approved_version_id"] = candidate.get("approved_version_id")
            records.append((c_approved, "candidate_approved", approved_payload))
        if c_rejected is not None:
            records.append((c_rejected, "candidate_rejected", dict(base_payload)))

    if status in {"success", "failed", "cancelled"} and finished_at is not None:
        records.append(
            (
                finished_at,
                "run_completed",
                {
                    "status": status,
                    "error_code": detail.get("error_code"),
                    "error_message": detail.get("error_message"),
                },
            )
        )

    # 稳定顺序：按时间、事件优先级、事件类型。
    records.sort(
        key=lambda item: (
            item[0],
            _EVENT_PRIORITY.get(item[1], 999),
            item[1],
        )
    )

    events: list[dict[str, Any]] = []
    for index, (ts, event_type, payload) in enumerate(records, start=1):
        ts_iso = ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        events.append(
            {
                "event_id": f"{run_id}:{index}",
                "run_id": run_id,
                "seq": index,
                "event_type": event_type,
                "ts": ts_iso,
                "payload": payload,
                "trace_id": trace_id,
            }
        )
    return events


def events_since_cursor(events: list[dict[str, Any]], cursor: int) -> list[dict[str, Any]]:
    threshold = max(0, int(cursor))
    return [event for event in events if int(event.get("seq") or 0) > threshold]


def terminal_status_reached(detail: dict[str, Any]) -> bool:
    return str(detail.get("status") or "").strip() in {"success", "failed", "cancelled"}


def last_seq(events: list[dict[str, Any]]) -> int:
    if not events:
        return 0
    return int(events[-1].get("seq") or 0)


def _parse_ts(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
