from __future__ import annotations

import re

from packages.retrieval.query_rewrite.base import QueryRewriter


class RuleQueryRewriter(QueryRewriter):
    """通用规则改写器（不引入业务词）。"""

    _MULTI_SPACE_RE = re.compile(r"\s+")
    _PUNCT_RE = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)
    _TOKEN_RE = re.compile(r"[a-z0-9]{2,}|[\u4e00-\u9fff]{2,}")
    _QUESTION_NOISE = (
        "请问",
        "一下",
        "一下子",
        "可能有什么",
        "会有什么",
        "有什么",
        "有何",
        "怎么",
        "怎样",
        "如何",
        "为什么",
        "是否",
        "有没有",
        "能不能",
        "可不可以",
        "可能",
        "会",
        "吗",
        "么",
        "呢",
    )

    def rewrite(self, query: str) -> list[str]:
        base = self._normalize(query)
        if not base:
            return []

        variants = [base]
        no_punct = self._normalize(self._PUNCT_RE.sub(" ", base))
        if no_punct:
            variants.append(no_punct)

        reduced = self._strip_noise(no_punct or base)
        if reduced:
            variants.append(reduced)

        keyword_variant = self._keywordize(reduced or no_punct or base)
        if keyword_variant:
            variants.append(keyword_variant)

        return self._dedupe_keep_order(variants)

    def _normalize(self, query: str) -> str:
        if not isinstance(query, str):
            return ""
        q = query.strip().lower()
        if not q:
            return ""
        return self._MULTI_SPACE_RE.sub(" ", q)

    def _strip_noise(self, query: str) -> str:
        q = query
        for phrase in self._QUESTION_NOISE:
            q = q.replace(phrase, " ")
        return self._normalize(q)

    def _keywordize(self, query: str) -> str:
        tokens = self._TOKEN_RE.findall(query)
        if not tokens:
            return ""

        out: list[str] = []
        seen: set[str] = set()
        for token in tokens:
            if token in self._QUESTION_NOISE or token in seen:
                continue
            seen.add(token)
            out.append(token)
            if len(out) >= 10:
                break

        return self._normalize(" ".join(out))

    @staticmethod
    def _dedupe_keep_order(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in items:
            if not item or item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out
