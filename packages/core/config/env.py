from __future__ import annotations

import os
from collections.abc import Mapping


def clamp(value: float, *, minimum: float | None = None, maximum: float | None = None) -> float:
    """将数值限制在给定范围。"""
    out = value
    if minimum is not None:
        out = max(out, minimum)
    if maximum is not None:
        out = min(out, maximum)
    return out


def _lookup(name: str, environ: Mapping[str, str] | None = None) -> str | None:
    source = os.environ if environ is None else environ
    value = source.get(name)
    if value is None:
        return None
    return value.strip()


def env_bool(
    name: str,
    default: bool,
    *,
    environ: Mapping[str, str] | None = None,
) -> bool:
    value = _lookup(name, environ)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_int(
    name: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    value = _lookup(name, environ)
    if value is None:
        out = default
    else:
        try:
            out = int(value)
        except ValueError:
            out = default

    if minimum is not None:
        out = max(out, minimum)
    if maximum is not None:
        out = min(out, maximum)
    return out


def env_float(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    environ: Mapping[str, str] | None = None,
) -> float:
    value = _lookup(name, environ)
    if value is None:
        out = default
    else:
        try:
            out = float(value)
        except ValueError:
            out = default

    return clamp(out, minimum=minimum, maximum=maximum)


def env_float_or_none(
    name: str,
    default: float | None,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    environ: Mapping[str, str] | None = None,
) -> float | None:
    value = _lookup(name, environ)
    if value is None:
        out = default
    else:
        lowered = value.lower()
        if lowered in {"", "none", "null"}:
            out = None
        else:
            try:
                out = float(lowered)
            except ValueError:
                out = default

    if out is None:
        return None
    return clamp(out, minimum=minimum, maximum=maximum)


def env_str(
    name: str,
    default: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> str:
    value = _lookup(name, environ)
    if value is None:
        return default
    return value or default


def env_str_or_none(
    name: str,
    default: str | None,
    *,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    value = _lookup(name, environ)
    if value is None:
        return default
    if not value:
        return default
    return value
