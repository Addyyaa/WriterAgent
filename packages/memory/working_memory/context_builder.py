from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from packages.core.utils import estimate_token_count
from packages.memory.short_term.session_memory import SessionMemorySummary
from packages.memory.working_memory.hybrid_compressor import HybridContextCompressor


@dataclass(frozen=True)
class ContextItem:
    source: str
    text: str
    priority: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextPackage:
    query: str
    token_budget: int
    used_tokens: int
    truncated: bool
    items: list[ContextItem]

    def to_retrieval_bundle(self) -> dict[str, Any]:
        """与编排检索 context_bundle 形状对齐：summary / items / meta（summary 由 retrieval_agent 负责语义）。"""
        return {
            "summary": {"key_facts": [], "current_states": []},
            "items": [
                {
                    "source": it.source,
                    "score": it.priority,
                    "text": it.text,
                }
                for it in self.items
            ],
            "meta": {
                "used_tokens": int(self.used_tokens),
                "truncated": bool(self.truncated),
                "token_budget": int(self.token_budget),
            },
        }


class ContextBuilder:
    """工作记忆构建器：做预算裁剪、去重与优先级编排。"""

    _SOURCE_PRIORITY = {
        "memory_fact": 1.0,
        "world_entry": 0.85,
        "chapter": 0.75,
        "session": 0.7,
        "working_note": 0.6,
        "unknown": 0.5,
    }
    _MIN_ITEM_BUDGET = 24
    _MAX_ITEM_BUDGET = 220

    def __init__(
        self,
        *,
        compressor: HybridContextCompressor | None = None,
        llm_max_items: int = 2,
        min_relevance_score: float = 0.58,
        relative_score_floor: float = 0.72,
        min_keep_rows: int = 3,
        max_rows: int = 32,
    ) -> None:
        self.compressor = compressor or HybridContextCompressor(enable_llm=False)
        self.llm_max_items = max(0, int(llm_max_items))
        self.min_relevance_score = max(0.0, min(1.0, float(min_relevance_score)))
        self.relative_score_floor = max(0.0, min(1.0, float(relative_score_floor)))
        self.min_keep_rows = max(1, int(min_keep_rows))
        self.max_rows = max(1, int(max_rows))

    def build(
        self,
        *,
        query: str,
        long_term_rows: list[dict] | None,
        session_summary: SessionMemorySummary | None,
        working_notes: list[str] | None = None,
        token_budget: int = 2000,
    ) -> ContextPackage:
        if token_budget <= 0:
            return ContextPackage(
                query=query,
                token_budget=token_budget,
                used_tokens=0,
                truncated=False,
                items=[],
            )

        candidates: list[ContextItem] = []
        filtered_long_term_rows = self._filter_long_term_rows(long_term_rows or [])

        for row in filtered_long_term_rows:
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            source_type = str(row.get("source_type") or "unknown")
            base_priority = self._SOURCE_PRIORITY.get(source_type, self._SOURCE_PRIORITY["unknown"])

            rank_boost = float(row.get("rerank_score") or row.get("hybrid_score") or 0.0)
            distance_penalty = float(row.get("distance") or 0.0)
            priority = base_priority + rank_boost - min(0.3, distance_penalty * 0.1)

            candidates.append(
                ContextItem(
                    source=source_type,
                    text=text,
                    priority=priority,
                    metadata={
                        "source_id": row.get("source_id"),
                        "chunk_type": row.get("chunk_type"),
                        "distance": row.get("distance"),
                        "hybrid_score": row.get("hybrid_score"),
                        "rerank_score": row.get("rerank_score"),
                        "context_confidence": row.get("_context_confidence"),
                        "summary_text": row.get("summary_text") or (row.get("metadata_json") or {}).get("summary_text"),
                    },
                )
            )

        if session_summary is not None:
            if session_summary.summary.strip():
                candidates.append(
                    ContextItem(
                        source="session",
                        text=session_summary.summary.strip(),
                        priority=self._SOURCE_PRIORITY["session"],
                        metadata={
                            "estimated_tokens": session_summary.estimated_tokens,
                            "facts": session_summary.key_facts,
                        },
                    )
                )

        for note in working_notes or []:
            text = str(note).strip()
            if not text:
                continue
            candidates.append(
                ContextItem(
                    source="working_note",
                    text=text,
                    priority=self._SOURCE_PRIORITY["working_note"],
                    metadata={},
                )
            )

        # 去重并按优先级排序。
        deduped = self._dedupe_by_text(candidates)
        deduped.sort(key=lambda x: (-x.priority, x.source))

        selected: list[ContextItem] = []
        used_tokens = 0
        truncated = False
        llm_remaining = self.llm_max_items

        total_candidates = max(1, len(deduped))
        dynamic_item_budget = min(
            self._MAX_ITEM_BUDGET,
            max(self._MIN_ITEM_BUDGET, token_budget // min(total_candidates, 8)),
        )

        for item in deduped:
            remaining = token_budget - used_tokens
            if remaining <= 0:
                truncated = True
                break

            target_budget = min(dynamic_item_budget, remaining)
            compression = self.compressor.compress(
                text=item.text,
                token_budget=target_budget,
                query=query,
                summary_hint=str(item.metadata.get("summary_text") or "").strip() or None,
                allow_llm=llm_remaining > 0,
            )
            compressed_text = compression.text
            method = compression.method
            if not compressed_text:
                truncated = True
                continue

            item_tokens = int(compression.compressed_tokens or estimate_token_count(compressed_text))
            if item_tokens > remaining:
                truncated = True
                continue

            if compression.llm_attempted:
                llm_remaining = max(0, llm_remaining - 1)

            if method != "none":
                metadata = dict(item.metadata or {})
                metadata["compression_method"] = method
                metadata["original_tokens"] = int(compression.original_tokens)
                metadata["compressed_tokens"] = int(compression.compressed_tokens)
                metadata["llm_attempted"] = bool(compression.llm_attempted)
                metadata["llm_used"] = bool(compression.llm_used)
                item = ContextItem(
                    source=item.source,
                    text=compressed_text,
                    priority=item.priority,
                    metadata=metadata,
                )
            selected.append(item)
            used_tokens += item_tokens

        return ContextPackage(
            query=query,
            token_budget=token_budget,
            used_tokens=used_tokens,
            truncated=truncated,
            items=selected,
        )

    def _filter_long_term_rows(self, rows: list[dict]) -> list[dict]:
        if not rows:
            return []

        limited = list(rows[: self.max_rows])
        confidences = self._compute_row_confidences(limited)
        if not confidences:
            return limited

        anchor = max(confidences)
        dynamic_floor = max(self.min_relevance_score, anchor * self.relative_score_floor)

        keep_flags = [score >= dynamic_floor for score in confidences]
        kept = [
            self._with_confidence(row, confidences[idx])
            for idx, (row, keep) in enumerate(zip(limited, keep_flags, strict=True))
            if keep
        ]

        if len(kept) >= self.min_keep_rows:
            return kept

        ranked_index = sorted(
            range(len(limited)),
            key=lambda idx: confidences[idx],
            reverse=True,
        )
        fallback_take = min(self.min_keep_rows, len(limited))
        selected_index = set(ranked_index[:fallback_take])
        return [
            self._with_confidence(row, confidences[idx])
            for idx, row in enumerate(limited)
            if idx in selected_index
        ]

    @staticmethod
    def _compute_row_confidences(rows: list[dict]) -> list[float]:
        max_hybrid = 0.0
        max_keyword = 0.0
        for row in rows:
            if row.get("hybrid_score") is not None:
                max_hybrid = max(max_hybrid, float(row.get("hybrid_score") or 0.0))
            if row.get("keyword_score") is not None:
                max_keyword = max(max_keyword, float(row.get("keyword_score") or 0.0))

        out: list[float] = []
        for row in rows:
            rerank = row.get("rerank_score")
            if rerank is not None:
                out.append(max(0.0, min(1.0, float(rerank))))
                continue

            hybrid = row.get("hybrid_score")
            if hybrid is not None and max_hybrid > 0:
                out.append(max(0.0, min(1.0, float(hybrid) / max_hybrid)))
                continue

            keyword = row.get("keyword_score")
            if keyword is not None and max_keyword > 0:
                out.append(max(0.0, min(1.0, float(keyword) / max_keyword)))
                continue

            distance = row.get("distance")
            if distance is not None:
                d = max(0.0, min(2.0, float(distance)))
                out.append(1.0 - (d / 2.0))
                continue

            out.append(0.0)
        return out

    @staticmethod
    def _with_confidence(row: dict, confidence: float) -> dict:
        item = dict(row)
        item["_context_confidence"] = float(confidence)
        return item

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, len(text) // 2) if text else 0

    @staticmethod
    def _dedupe_by_text(items: list[ContextItem]) -> list[ContextItem]:
        out: list[ContextItem] = []
        seen: set[str] = set()
        for item in items:
            key = item.text.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out
