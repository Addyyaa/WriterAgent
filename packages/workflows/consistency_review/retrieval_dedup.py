"""检索证据与 review_context 去重，降低与 DB 证据包的语义重复。"""

from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}")

# 与证据 token 集合 Jaccard 超过此值则丢弃检索项（略保守，避免误删）
_JACCARD_DROP = 0.52


def _normalize(s: str) -> str:
    return " ".join(str(s or "").lower().split())


def _token_set(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(str(text or ""))[:500])


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return float(inter) / float(union) if union else 0.0


def _evidence_snippets_from_review_context(review_context: dict[str, Any]) -> tuple[list[str], list[set[str]]]:
    """返回归一化片段列表与 token 集合列表，用于包含关系与 Jaccard。"""
    snippets: list[str] = []
    token_sets: list[set[str]] = []

    def add_blob(blob: str) -> None:
        b = str(blob or "").strip()
        if len(b) < 12:
            return
        snippets.append(_normalize(b))
        token_sets.append(_token_set(b))

    for w in list(review_context.get("world_entries") or []):
        if isinstance(w, dict):
            add_blob(str(w.get("title") or "") + " " + str(w.get("content") or ""))

    for ev in list(review_context.get("timeline_events") or []):
        if isinstance(ev, dict):
            add_blob(str(ev.get("event_title") or "") + " " + str(ev.get("event_desc") or ""))

    for fs in list(review_context.get("foreshadowings") or []):
        if isinstance(fs, dict):
            add_blob(
                str(fs.get("setup_text") or "")
                + " "
                + str(fs.get("expected_payoff") or "")
            )

    for ch in list(review_context.get("chapters") or []):
        if isinstance(ch, dict):
            add_blob(
                str(ch.get("title") or "")
                + " "
                + str(ch.get("summary") or "")
                + " "
                + str(ch.get("content_preview") or "")
            )

    for c in list(review_context.get("characters") or []):
        if isinstance(c, dict):
            add_blob(str(c.get("name") or ""))

    return snippets, token_sets


def dedupe_retrieval_bundle_against_evidence(
    bundle: dict[str, Any],
    review_context: dict[str, Any],
) -> dict[str, Any]:
    """去掉与 review_context 高度重叠的 retrieval.items（保留 summary/meta）。"""
    out = dict(bundle or {})
    items = list(out.get("items") or [])
    if not items:
        return out

    snippets, token_sets = _evidence_snippets_from_review_context(review_context)
    if not snippets and not token_sets:
        return out

    kept: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            kept.append(item)
            continue
        norm_item = _normalize(text)
        item_toks = _token_set(text)
        drop = False
        for snip in snippets:
            if len(snip) >= 20 and (snip in norm_item or norm_item in snip):
                drop = True
                break
        if not drop:
            for ts in token_sets:
                if _jaccard(item_toks, ts) >= _JACCARD_DROP:
                    drop = True
                    break
        if not drop:
            kept.append(dict(item))

    out["items"] = kept
    meta = dict(out.get("meta") or {})
    meta["retrieval_dedup_removed"] = int(len(items) - len(kept))
    out["meta"] = meta
    return out
