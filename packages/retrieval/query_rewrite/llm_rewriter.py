from __future__ import annotations

from typing import Callable

from packages.retrieval.query_rewrite.base import QueryRewriter


class LLMQueryRewriter(QueryRewriter):
    """可注入外部 LLM 改写函数的适配器。"""

    def __init__(self, rewrite_fn: Callable[[str], list[str]]) -> None:
        self.rewrite_fn = rewrite_fn

    def rewrite(self, query: str) -> list[str]:
        if not query.strip():
            return []
        try:
            variants = self.rewrite_fn(query)
        except Exception:
            return [query]
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in variants or []:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        return cleaned or [query]
