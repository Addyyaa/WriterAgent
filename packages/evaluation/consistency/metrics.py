from __future__ import annotations


def status_to_score(status: str | None) -> float:
    normalized = str(status or "").strip().lower()
    if normalized == "passed":
        return 1.0
    if normalized == "warning":
        return 0.6
    if normalized == "failed":
        return 0.2
    return 0.0
