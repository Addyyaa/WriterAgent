from __future__ import annotations

from collections.abc import Iterable
import re
from typing import Any


_CJK_OR_WORD_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{1,4}")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?\\n])")
_STOP_TERMS = {
    "什么",
    "如何",
    "怎么",
    "哪些",
    "以及",
    "这个",
    "那个",
    "我们",
    "你们",
    "他们",
    "是否",
    "一下",
    "the",
    "a",
    "an",
    "of",
    "to",
    "for",
    "and",
    "or",
    "is",
    "are",
}

_TIKTOKEN_ENCODER: Any | None = None
_TIKTOKEN_INIT_DONE = False


def normalize_whitespace(text: str) -> str:
    """合并连续空白字符并去除首尾空白。"""
    return " ".join(text.split())


def ensure_non_empty_string(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} 必须是字符串")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} 不能为空")
    return normalized


def dedupe_keep_order(items: Iterable[str]) -> list[str]:
    """保持输入顺序去重并自动去除空白项。"""
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = item.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def estimate_token_count(text: str) -> int:
    if not text:
        return 0
    encoder = _get_tiktoken_encoder()
    if encoder is not None:
        try:
            return max(1, len(encoder.encode(text)))
        except Exception:
            pass
    # 中英文混合下的保守经验值：2 字符约 1 token（tiktoken 不可用时回退）。
    return max(1, len(text) // 2)


def _get_tiktoken_encoder():
    global _TIKTOKEN_ENCODER, _TIKTOKEN_INIT_DONE
    if _TIKTOKEN_INIT_DONE:
        return _TIKTOKEN_ENCODER
    _TIKTOKEN_INIT_DONE = True
    try:
        import tiktoken  # type: ignore

        # 使用通用 cl100k_base，兼容大多数现代模型的近似计数。
        _TIKTOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")
    except Exception:
        _TIKTOKEN_ENCODER = None
    return _TIKTOKEN_ENCODER


def split_sentences(text: str) -> list[str]:
    if not text:
        return []
    segments = _SENTENCE_SPLIT_RE.split(text)
    out: list[str] = []
    for segment in segments:
        item = segment.strip()
        if item:
            out.append(item)
    return out or [text.strip()]


def extract_query_terms(query: str, *, max_terms: int = 16) -> list[str]:
    if not isinstance(query, str):
        return []
    tokens = [item.lower().strip() for item in _CJK_OR_WORD_RE.findall(query)]
    out: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if len(token) <= 1 or token in _STOP_TERMS or token in seen:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= max_terms:
            break
    return out


def summarize_text_extractive(
    text: str,
    *,
    query: str | None = None,
    target_tokens: int = 120,
    min_sentences: int = 1,
    max_sentences: int = 6,
) -> str:
    normalized = normalize_whitespace(text or "")
    if not normalized:
        return ""
    if target_tokens <= 0:
        return ""
    if estimate_token_count(normalized) <= target_tokens:
        return normalized

    sentences = split_sentences(normalized)
    if not sentences:
        return normalized

    query_terms = set(extract_query_terms(query or ""))
    scored: list[tuple[float, int, str]] = []
    for idx, sentence in enumerate(sentences):
        score = _score_sentence(sentence=sentence, query_terms=query_terms, index=idx)
        scored.append((score, idx, sentence))

    scored.sort(key=lambda x: (-x[0], x[1]))
    selected: list[tuple[int, str]] = []
    used = 0
    for _, idx, sentence in scored:
        if len(selected) >= max_sentences:
            break
        cost = estimate_token_count(sentence)
        if selected and used + cost > target_tokens:
            continue
        selected.append((idx, sentence))
        used += cost
        if used >= target_tokens:
            break

    if len(selected) < min_sentences:
        selected = [(0, sentences[0])]

    selected.sort(key=lambda x: x[0])
    summary = normalize_whitespace(" ".join(item[1] for item in selected))
    if estimate_token_count(summary) <= target_tokens:
        return summary

    max_chars = max(16, target_tokens * 2)
    return summary[: max_chars - 3].rstrip() + "..."


def compress_text_to_budget(
    text: str,
    *,
    token_budget: int,
    query: str | None = None,
    fallback_summary: str | None = None,
) -> tuple[str, str]:
    normalized = normalize_whitespace(text or "")
    if token_budget <= 0 or not normalized:
        return "", "empty"
    if estimate_token_count(normalized) <= token_budget:
        return normalized, "none"

    if fallback_summary:
        compact_summary = normalize_whitespace(fallback_summary)
        if compact_summary and estimate_token_count(compact_summary) <= token_budget:
            return compact_summary, "summary_hint"

    extractive = summarize_text_extractive(
        normalized,
        query=query,
        target_tokens=max(24, token_budget),
        min_sentences=1,
        max_sentences=6,
    )
    if extractive and estimate_token_count(extractive) <= token_budget:
        return extractive, "extractive"

    max_chars = max(16, token_budget * 2)
    return normalized[: max_chars - 3].rstrip() + "...", "truncate"


def _score_sentence(*, sentence: str, query_terms: set[str], index: int) -> float:
    lowered = sentence.lower()
    overlap = 0
    for term in query_terms:
        if term in lowered:
            overlap += 1

    punctuation_bonus = 0.2 if sentence.endswith(("。", ".", "！", "!", "？", "?")) else 0.0
    position_bonus = max(0.0, 0.3 - (index * 0.03))
    length_penalty = 0.0
    if len(sentence) < 12:
        length_penalty = 0.25
    elif len(sentence) > 240:
        length_penalty = 0.2

    return (overlap * 1.2) + punctuation_bonus + position_bonus - length_penalty
