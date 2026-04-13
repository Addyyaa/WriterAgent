from __future__ import annotations

import math
from collections import Counter, defaultdict
from threading import Lock
from typing import Iterable


class InMemoryMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: Counter[tuple[str, tuple[tuple[str, str], ...]]] = Counter()
        self._histograms: defaultdict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = defaultdict(list)

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] += float(value)

    def observe(self, name: str, value: float, **labels: str) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._histograms[key].append(float(value))

    def snapshot(self) -> tuple[dict, dict]:
        with self._lock:
            return dict(self._counters), {k: list(v) for k, v in self._histograms.items()}

    @staticmethod
    def _key(name: str, labels: dict[str, str]) -> tuple[str, tuple[tuple[str, str], ...]]:
        normalized = tuple(sorted((str(k), str(v)) for k, v in labels.items()))
        return (name, normalized)


def render_prometheus(counters: dict, histograms: dict) -> str:
    lines: list[str] = []
    for (name, labels), value in sorted(counters.items(), key=lambda x: x[0][0]):
        lines.append(f"{name}{_fmt_labels(labels)} {float(value):.6f}")

    for (name, labels), values in sorted(histograms.items(), key=lambda x: x[0][0]):
        if not values:
            continue
        count = len(values)
        s = sum(values)
        p95 = _percentile(values, 0.95)
        lines.append(f"{name}_count{_fmt_labels(labels)} {count}")
        lines.append(f"{name}_sum{_fmt_labels(labels)} {s:.6f}")
        lines.append(f"{name}_p95{_fmt_labels(labels)} {p95:.6f}")

    return "\n".join(lines) + "\n"


def _fmt_labels(labels: Iterable[tuple[str, str]]) -> str:
    labels = list(labels)
    if not labels:
        return ""
    body = ",".join(f'{k}="{v}"' for k, v in labels)
    return f"{{{body}}}"


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(math.ceil(q * len(ordered))) - 1))
    return float(ordered[idx])
