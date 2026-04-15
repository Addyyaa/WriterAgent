from __future__ import annotations

from typing import Any

from packages.memory.long_term.search.search_service import MemorySearchService
from packages.memory.short_term.session_memory import SessionMemoryService
from packages.memory.working_memory.context_builder import ContextBuilder, ContextPackage


class ProjectMemoryService:
    """统一组装 long/short/working memory 的项目级入口。"""

    def __init__(
        self,
        long_term_search: MemorySearchService,
        session_memory: SessionMemoryService | None = None,
        context_builder: ContextBuilder | None = None,
    ) -> None:
        self.long_term_search = long_term_search
        self.session_memory = session_memory or SessionMemoryService()
        self.context_builder = context_builder or ContextBuilder()

    def build_context(
        self,
        *,
        project_id,
        query: str,
        token_budget: int = 2000,
        top_k: int = 8,
        chat_turns: list[dict[str, Any]] | None = None,
        working_notes: list[str] | None = None,
        source_type: str | None = None,
        chunk_type: str | None = None,
        sort_by: str = "relevance_then_recent",
        max_distance: float | None = None,
        fallback_max_distance: float | None = None,
        enable_query_rewrite: bool = True,
        enable_hybrid: bool = True,
        enable_rerank: bool = True,
    ) -> ContextPackage:
        long_term_rows = self.long_term_search.search_with_scores(
            project_id=project_id,
            query=query,
            top_k=top_k,
            source_type=source_type,
            chunk_type=chunk_type,
            sort_by=sort_by,
            max_distance=max_distance,
            fallback_max_distance=fallback_max_distance,
            enable_query_rewrite=enable_query_rewrite,
            enable_hybrid=enable_hybrid,
            enable_rerank=enable_rerank,
        )

        short_budget = max(200, token_budget // 4)
        session_summary = self.session_memory.compress(
            turns=chat_turns or [],
            token_budget=short_budget,
        )

        return self.context_builder.build(
            query=query,
            long_term_rows=long_term_rows,
            session_summary=session_summary,
            working_notes=working_notes,
            token_budget=token_budget,
        )

    def build_context_as_retrieval_bundle(self, **kwargs: Any) -> dict[str, Any]:
        """`build_context` 的便捷封装，返回与检索循环一致的 context_bundle 字典。"""
        return self.build_context(**kwargs).to_retrieval_bundle()
