from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class OnlineEvalEvent:
    user_id: str
    query: str
    variant: str
    clicked: bool


@dataclass(frozen=True)
class VariantStats:
    variant: str
    impressions: int
    clicks: int
    ctr: float


class OnlineEvaluator:
    """在线评测基础实现（A/B 分流 + CTR 聚合）。"""

    def __init__(self, variants: list[str] | None = None) -> None:
        self.variants = variants or ["A", "B"]
        self._impressions: dict[str, int] = {variant: 0 for variant in self.variants}
        self._clicks: dict[str, int] = {variant: 0 for variant in self.variants}

    def assign_variant(self, *, user_id: str, query: str) -> str:
        key = f"{user_id}:{query}".encode("utf-8")
        digest = hashlib.sha256(key).hexdigest()
        index = int(digest[:8], 16) % len(self.variants)
        return self.variants[index]

    def record(self, event: OnlineEvalEvent) -> None:
        if event.variant not in self._impressions:
            return
        self._impressions[event.variant] += 1
        if event.clicked:
            self._clicks[event.variant] += 1

    def report(self) -> list[VariantStats]:
        rows: list[VariantStats] = []
        for variant in self.variants:
            impressions = self._impressions.get(variant, 0)
            clicks = self._clicks.get(variant, 0)
            ctr = (clicks / impressions) if impressions else 0.0
            rows.append(
                VariantStats(
                    variant=variant,
                    impressions=impressions,
                    clicks=clicks,
                    ctr=ctr,
                )
            )
        return rows
