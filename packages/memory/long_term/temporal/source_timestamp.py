from __future__ import annotations

from datetime import datetime, timezone

SOURCE_TIMESTAMP_KEY = "source_timestamp"


def normalize_source_timestamp(value) -> str | None:
    """
    规范化 source_timestamp。

    约定：
    - None / 空字符串 -> None
    - datetime -> 转 UTC 后输出 ISO8601（`Z` 后缀）
    - str(ISO8601) -> 解析后转 UTC ISO8601（`Z` 后缀）

    说明：
    - 这里不做“文本时间抽取”，只处理上游已提供的时间值。
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        dt = _parse_iso8601(raw)
    else:
        raise ValueError(
            "source_timestamp 必须是 ISO8601 字符串、datetime 或 None"
        )

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def source_timestamp_to_epoch(value) -> float | None:
    """
    将 source_timestamp 转成 epoch 秒，便于排序。
    """
    normalized = normalize_source_timestamp(value)
    if normalized is None:
        return None
    dt = _parse_iso8601(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _parse_iso8601(value: str) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(
            f"source_timestamp 非法，需 ISO8601 格式：{value}"
        ) from exc

