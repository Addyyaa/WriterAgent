"""修订步：限制 context_bundle.items 来源与条数，避免宽检索灌入无关片段。"""

from __future__ import annotations

from typing import Any

from packages.core.context_bundle_decision import mirror_context_bundle_lists_from_summary

# 与 EvidenceItem / 检索 items 的 source 字段对齐
REVISION_RETRIEVAL_ALLOWED_SOURCES: frozenset[str] = frozenset(
    {
        "memory_fact",
        "chapter",
        "character_inventory",
        "story_state_snapshot",
    }
)


def filter_revision_context_bundle_items(
    bundle: dict[str, Any],
    *,
    max_items: int = 8,
) -> None:
    """就地过滤 ``bundle['items']``，仅保留白名单来源，按 score 降序截断。"""
    raw = list(bundle.get("items") or [])
    candidates: list[dict[str, Any]] = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        src = str(it.get("source") or "").strip().lower()
        if src not in REVISION_RETRIEVAL_ALLOWED_SOURCES:
            continue
        candidates.append(dict(it))
    candidates.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    bundle["items"] = candidates[: max(0, int(max_items))]
    mirror_context_bundle_lists_from_summary(bundle)
