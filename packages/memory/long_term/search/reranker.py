from __future__ import annotations

from dataclasses import dataclass
import re

from packages.memory.long_term.temporal import SOURCE_TIMESTAMP_KEY, source_timestamp_to_epoch
from packages.retrieval.keyword.analyzer import SimpleAnalyzer


@dataclass(frozen=True)
class RuleRerankerConfig:
    """
    规则重排配置。

    - vector_weight: 向量相关性权重（distance -> relevance）
    - keyword_weight: 关键词召回权重（hybrid/fts 命中增强）
    - recency_weight: 时间新鲜度权重（用于冲突信息优先级）
    - query_overlap_weight: query 与候选文本重叠度权重
    - canonical_fact_boost: 规范事实轻微加权
    - contradiction_penalty: 否定语义惩罚
    """

    vector_weight: float = 0.62
    keyword_weight: float = 0.18
    recency_weight: float = 0.08
    query_overlap_weight: float = 0.12
    canonical_fact_boost: float = 0.03
    contradiction_penalty: float = 0.16


class RuleBasedReranker:
    """
    轻量规则重排器。

    当前目标：
    - 在不引入重模型推理成本的前提下，提升相关性稳定性。
    - 给出可解释分数字段，方便线上诊断与调参。
    """

    _NEGATIVE_CUES = (
        "无直接推进",
        "不触发",
        "未涉及",
        "不涉及",
        "误报",
        "无关",
        "弱相关",
        "并不一致",
        "暂时中止",
    )
    _CJK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")

    def __init__(self, config: RuleRerankerConfig | None = None) -> None:
        self.config = config or RuleRerankerConfig()
        self._analyzer = SimpleAnalyzer()

    def rerank(
        self,
        rows: list[dict],
        *,
        sort_by: str,
        top_k: int,
        query: str | None = None,
    ) -> list[dict]:
        if not rows or top_k <= 0:
            return []

        if sort_by not in {"distance", "distance_then_source_timestamp_desc"}:
            return rows[:top_k]

        query_tokens = self._tokenize_query(query or "")
        max_keyword_score = max(float(item.get("keyword_score") or 0.0) for item in rows)
        ts_values = [source_timestamp_to_epoch(item.get(SOURCE_TIMESTAMP_KEY)) for item in rows]
        valid_ts = [v for v in ts_values if v is not None]
        min_ts = min(valid_ts) if valid_ts else None
        max_ts = max(valid_ts) if valid_ts else None

        ranked: list[dict] = []
        for row in rows:
            item = dict(row)
            vector_relevance = self._vector_relevance(item.get("distance"))
            keyword_relevance = self._keyword_relevance(
                item.get("keyword_score"),
                max_keyword_score=max_keyword_score,
            )
            recency_relevance = self._recency_relevance(
                item.get(SOURCE_TIMESTAMP_KEY),
                min_ts=min_ts,
                max_ts=max_ts,
            )
            query_overlap = self._query_overlap_relevance(
                query_tokens=query_tokens,
                text=str(item.get("text") or ""),
                summary_text=str(item.get("summary_text") or ""),
            )
            contradiction_penalty = self._contradiction_penalty(
                query_tokens=query_tokens,
                text=str(item.get("text") or ""),
                summary_text=str(item.get("summary_text") or ""),
                overlap=query_overlap,
            )
            source_boost = (
                self.config.canonical_fact_boost if item.get("source_type") == "memory_fact" else 0.0
            )

            rerank_score = (
                self.config.vector_weight * vector_relevance
                + self.config.keyword_weight * keyword_relevance
                + self.config.recency_weight * recency_relevance
                + self.config.query_overlap_weight * query_overlap
                + source_boost
                - contradiction_penalty
            )
            item["rerank_score"] = float(max(0.0, rerank_score))
            ranked.append(item)

        if sort_by == "distance_then_source_timestamp_desc":
            ranked.sort(
                key=lambda x: (
                    -(x.get("rerank_score") or 0.0),
                    source_timestamp_to_epoch(x.get(SOURCE_TIMESTAMP_KEY)) is None,
                    -(source_timestamp_to_epoch(x.get(SOURCE_TIMESTAMP_KEY)) or 0.0),
                    x.get("distance", 1.0),
                )
            )
        else:
            ranked.sort(
                key=lambda x: (
                    -(x.get("rerank_score") or 0.0),
                    x.get("distance", 1.0),
                )
            )
        return ranked[:top_k]

    def _tokenize_query(self, query: str) -> set[str]:
        tokens = self._analyzer.tokenize(query or "")
        return {token for token in tokens if self._CJK_RE.search(token)}

    @staticmethod
    def _vector_relevance(distance) -> float:
        if distance is None:
            return 0.0
        d = float(distance)
        d = min(max(d, 0.0), 2.0)
        return 1.0 - (d / 2.0)

    @staticmethod
    def _keyword_relevance(keyword_score, *, max_keyword_score: float) -> float:
        if max_keyword_score <= 0:
            return 0.0
        return float(keyword_score or 0.0) / max_keyword_score

    @staticmethod
    def _recency_relevance(source_timestamp, *, min_ts: float | None, max_ts: float | None) -> float:
        if min_ts is None or max_ts is None:
            return 0.0
        ts = source_timestamp_to_epoch(source_timestamp)
        if ts is None:
            return 0.0
        if max_ts == min_ts:
            return 1.0
        return (ts - min_ts) / (max_ts - min_ts)

    def _query_overlap_relevance(
        self,
        *,
        query_tokens: set[str],
        text: str,
        summary_text: str,
    ) -> float:
        if not query_tokens:
            return 0.0
        hay = f"{summary_text} {text}".strip()
        if not hay:
            return 0.0
        doc_tokens = set(self._analyzer.tokenize(hay))
        if not doc_tokens:
            return 0.0
        overlap = len(query_tokens & doc_tokens)
        return overlap / max(1, len(query_tokens))

    def _contradiction_penalty(
        self,
        *,
        query_tokens: set[str],
        text: str,
        summary_text: str,
        overlap: float,
    ) -> float:
        if overlap <= 0 or not query_tokens:
            return 0.0
        hay = f"{summary_text} {text}"
        if not hay:
            return 0.0
        if not any(cue in hay for cue in self._NEGATIVE_CUES):
            return 0.0
        return self.config.contradiction_penalty * (0.5 + 0.5 * overlap)

