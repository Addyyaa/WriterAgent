from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator
from uuid import uuid4

_REQUEST_ID: ContextVar[str | None] = ContextVar("writeragent_request_id", default=None)
_TRACE_ID: ContextVar[str | None] = ContextVar("writeragent_trace_id", default=None)


def get_request_id() -> str | None:
    return _REQUEST_ID.get()


def get_trace_id() -> str | None:
    return _TRACE_ID.get()


def set_request_id(value: str) -> Token[str | None]:
    return _REQUEST_ID.set(value)


def set_trace_id(value: str) -> Token[str | None]:
    return _TRACE_ID.set(value)


def reset_request_id(token: Token[str | None]) -> None:
    _REQUEST_ID.reset(token)


def reset_trace_id(token: Token[str | None]) -> None:
    _TRACE_ID.reset(token)


def clear_request_id() -> None:
    _REQUEST_ID.set(None)


def clear_trace_id() -> None:
    _TRACE_ID.set(None)


def _new_id() -> str:
    return str(uuid4())


def new_request_id() -> str:
    return _new_id()


def new_trace_id() -> str:
    return _new_id()


@contextmanager
def request_context(
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
) -> Iterator[tuple[str, str]]:
    """在 with 块内注入 request_id/trace_id。"""
    effective_request_id = request_id or new_request_id()
    effective_trace_id = trace_id or new_trace_id()

    request_token = set_request_id(effective_request_id)
    trace_token = set_trace_id(effective_trace_id)
    try:
        yield effective_request_id, effective_trace_id
    finally:
        reset_trace_id(trace_token)
        reset_request_id(request_token)
