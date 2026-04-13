from __future__ import annotations

import json
import logging
from collections import Counter
from threading import Lock
from typing import Any

from packages.core.tracing import get_request_id, get_trace_id
from packages.core.utils.time import utc_now_iso


class StructuredObservability:
    """结构化日志 + 线程安全计数器。"""

    def __init__(
        self,
        logger_name: str = "writeragent",
        *,
        enable_logging: bool = True,
        include_trace_context: bool = True,
    ) -> None:
        self.logger = logging.getLogger(logger_name)
        self.enable_logging = enable_logging
        self.include_trace_context = include_trace_context
        self._counter: Counter[str] = Counter()
        self._lock = Lock()

    def incr(self, metric: str, value: int = 1) -> None:
        if value == 0:
            return
        with self._lock:
            self._counter[metric] += int(value)

    def emit(self, event: str, **fields: Any) -> None:
        if not self.enable_logging:
            return

        payload: dict[str, Any] = {
            "ts": utc_now_iso(),
            "event": event,
        }
        payload.update(fields)

        if self.include_trace_context:
            request_id = get_request_id()
            trace_id = get_trace_id()
            if request_id is not None and "request_id" not in payload:
                payload["request_id"] = request_id
            if trace_id is not None and "trace_id" not in payload:
                payload["trace_id"] = trace_id

        msg = self._to_json(payload)
        self.logger.info(msg)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counter)

    @staticmethod
    def _to_json(payload: dict[str, Any]) -> str:
        safe_payload = _redact_sensitive(payload)
        try:
            return json.dumps(safe_payload, ensure_ascii=False, default=str)
        except TypeError:
            # 防御式降级，避免不可序列化字段中断主链。
            fallback_payload = {
                key: (
                    value
                    if isinstance(value, (str, int, float, bool, type(None), list, dict))
                    else str(value)
                )
                for key, value in safe_payload.items()
            }
            return json.dumps(fallback_payload, ensure_ascii=False, default=str)


_SENSITIVE_KEYWORDS = (
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "authorization",
)


def _redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            lowered = key.lower()
            if any(item in lowered for item in _SENSITIVE_KEYWORDS):
                out[key] = "***REDACTED***"
            else:
                out[key] = _redact_sensitive(v)
        return out
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value
