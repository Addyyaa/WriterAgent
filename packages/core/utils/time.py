from __future__ import annotations

from datetime import datetime, timezone


def utc_now_iso() -> str:
    """返回 ISO8601 UTC 时间，结尾为 Z。"""
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
