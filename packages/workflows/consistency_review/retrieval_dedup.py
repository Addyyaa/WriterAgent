"""检索证据与 review_context 去重，降低与 DB 证据包的语义重复。"""

from __future__ import annotations

import re
from typing import Any

from packages.core.context_bundle_decision import mirror_context_bundle_lists_from_summary

_TOKEN_RE = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}")

# 与证据 token 集合 Jaccard 超过此值则丢弃检索项（略保守，避免误删）
_JACCARD_DROP = 0.52

# 大纲/目录式噪声：避免整段 outline 混入 supporting_evidence / facts
_OUTLINE_HINT_RE = re.compile(
    r"(第[一二三四五六七八九十百千零\d]+章|第\s*\d+\s*章|章节目录|故事大纲|剧情大纲|\boutline\b|卷[一二三四五六七八九十百千\d])",
    re.IGNORECASE,
)


def _outline_noise_score(text: str) -> float:
    t = str(text or "").strip()
    if not t:
        return 0.0
    score = 0.0
    if _OUTLINE_HINT_RE.search(t):
        score += 2.25
    if t.count("章") >= 4:
        score += 1.75
    if len(t) > 520 and "\n" in t and t.count("\n") >= 4:
        score += 1.25
    if len(t) > 900 and t.count("。") <= 1 and score >= 1.0:
        score += 0.75
    return score


def _should_drop_outline_summary_line(field_key: str, text: str) -> bool:
    t = str(text or "").strip()
    if not t:
        return True
    sc = _outline_noise_score(t)
    if sc >= 3.0:
        return True
    if sc >= 2.0 and len(t) > 120:
        return True
    if field_key == "supporting_evidence" and sc >= 1.25 and len(t) > 90:
        return True
    if field_key in {"key_facts", "confirmed_facts"} and sc >= 2.25 and len(t) > 200:
        return True
    return False


def _filter_outline_noise_strings(items: list[str], *, field_key: str) -> list[str]:
    return [x for x in items if not _should_drop_outline_summary_line(field_key, x)]


def _dedupe_summary_lists_globally(summary: dict[str, Any]) -> None:
    """跨列表去重：优先保留靠前字段中的条目（confirmed > key_facts > …）。"""
    priority = [
        "confirmed_facts",
        "key_facts",
        "current_states",
        "supporting_evidence",
        "information_gaps",
    ]
    seen_norm: set[str] = set()
    for key in priority:
        raw = summary.get(key)
        if not isinstance(raw, list):
            continue
        kept: list[str] = []
        for x in raw:
            sx = str(x).strip()
            if len(sx) < 12:
                kept.append(sx)
                continue
            n = _normalize(sx)
            if len(n) < 14:
                kept.append(sx)
                continue
            if n in seen_norm:
                continue
            seen_norm.add(n)
            kept.append(sx)
        summary[key] = kept


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
            nm = str(c.get("name") or "").strip()
            parts = [nm]
            pj = c.get("profile_json")
            if isinstance(pj, dict):
                for a, b in list(pj.items())[:24]:
                    if b is None:
                        continue
                    parts.append(f"{a}={b}")
            add_blob(" ".join(parts)[:2400])
            pa = c.get("profile_audit")
            if isinstance(pa, dict):
                add_blob(nm + " " + " ".join(str(v) for v in pa.values() if v is not None)[:2000])

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


def _clean_snippet_start(s: str) -> str:
    """弱化「从句中截断」起首：去掉前导标点与不完整碎片。"""
    t = str(s or "").strip()
    while t and t[0] in ",.;:，。、；：（）()[]{}「」『』\"'":
        t = t[1:].lstrip()
    if t.startswith("，"):
        t = t[1:].strip()
    return t


def _dedupe_string_list(
    items: list[Any],
    *,
    max_len: int,
    max_items: int,
    min_chars: int = 8,
) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        s = _clean_snippet_start(str(raw or ""))
        if len(s) < min_chars:
            continue
        norm = _normalize(s)
        if len(norm) < min_chars or norm in seen:
            continue
        seen.add(norm)
        out.append(s[:max_len] if len(s) > max_len else s)
        if len(out) >= max_items:
            break
    return out


def sanitize_consistency_retrieval_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """一致性审查专用：摘要列表去重截断、弱化 outline 长段、items 去重并限制条数。"""
    out = dict(bundle or {})
    summary = dict(out.get("summary") or {})

    list_caps = {
        "key_facts": (360, 22),
        "current_states": (360, 20),
        "confirmed_facts": (360, 22),
        "supporting_evidence": (300, 16),
        "information_gaps": (320, 14),
    }
    for key, (lim, cap) in list_caps.items():
        raw = summary.get(key)
        if isinstance(raw, list):
            min_c = 12 if key == "supporting_evidence" else 8
            cleaned = _dedupe_string_list(raw, max_len=lim, max_items=cap, min_chars=min_c)
            summary[key] = _filter_outline_noise_strings(cleaned, field_key=key)

    _dedupe_summary_lists_globally(summary)

    conflicts = summary.get("conflicts")
    if isinstance(conflicts, list):
        cleaned_conf: list[Any] = []
        seen_c: set[str] = set()
        for c in conflicts:
            if isinstance(c, dict):
                desc = _clean_snippet_start(str(c.get("description") or c))
                if len(desc) < 8:
                    continue
                n = _normalize(desc)
                if n in seen_c:
                    continue
                seen_c.add(n)
                cpy = dict(c)
                cpy["description"] = desc[:400]
                cleaned_conf.append(cpy)
            else:
                s = _clean_snippet_start(str(c))
                if len(s) >= 8 and _normalize(s) not in seen_c:
                    seen_c.add(_normalize(s))
                    cleaned_conf.append(s[:400])
            if len(cleaned_conf) >= 12:
                break
        summary["conflicts"] = cleaned_conf

    out["summary"] = summary

    items = list(out.get("items") or [])
    kept: list[dict[str, Any]] = []
    seen_txt: set[str] = set()
    outline_kept = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        src = str(it.get("source") or "").strip().lower()
        text = _clean_snippet_start(str(it.get("text") or ""))
        if not text:
            continue
        if _outline_noise_score(text) >= 2.5 and len(text) > 180:
            if src in {"outline", "project", "outline_chunk", "plan"}:
                continue
        if src in {"outline", "project"}:
            if outline_kept >= 1 and len(text) > 200:
                continue
            if len(text) > 360 or text.count("\n") > 6:
                continue
            text = text[:280]
            outline_kept += 1
        elif len(text) > 420:
            text = text[:400]
        norm = _normalize(text)
        if len(norm) < 12 or norm in seen_txt:
            continue
        seen_txt.add(norm)
        cpy = dict(it)
        cpy["text"] = text
        kept.append(cpy)
        if len(kept) >= 8:
            break
    out["items"] = kept

    mirror_context_bundle_lists_from_summary(out)
    meta = dict(out.get("meta") or {})
    meta["retrieval_sanitized"] = True
    out["meta"] = meta
    return out
