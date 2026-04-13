from __future__ import annotations

from dataclasses import dataclass
import re

from packages.memory.long_term.temporal import source_timestamp_to_epoch
from packages.retrieval.keyword.analyzer import SimpleAnalyzer
from packages.retrieval.rerank.base import Reranker
from packages.retrieval.types import ScoredDoc


@dataclass(frozen=True)
class RuleBasedRerankConfig:
    """
    规则重排配置。

    评分由五个部分组成：
    1) 向量相关性（distance -> relevance）
    2) 关键词相关性（keyword_score 归一化）
    3) 时间新鲜度（source_timestamp）
    4) query-overlap（任务语义相关性）
    5) 规范事实轻微加权（canonical_fact_boost）

    同时引入 contradiction_penalty，用于压制“语义相关但回答无效/否定”的噪声文档。
    """

    vector_weight: float = 0.62
    keyword_weight: float = 0.18
    recency_weight: float = 0.08
    query_overlap_weight: float = 0.12
    canonical_fact_boost: float = 0.03
    contradiction_penalty: float = 0.16


class RuleBasedReranker(Reranker):
    """
    轻量规则重排器（可解释、低成本）。

    适用场景：
    - 默认线上主链（无需外部重排服务即可工作）
    - 对稳定性和成本敏感的场景
    - 需要可解释打分和快速调参的场景
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

    def __init__(self, config: RuleBasedRerankConfig | None = None) -> None:
        self.config = config or RuleBasedRerankConfig()
        self._analyzer = SimpleAnalyzer()

    def rerank(
        self,
        *,
        query: str,
        candidates: list[ScoredDoc],
        top_k: int,
        sort_by: str,
    ) -> list[ScoredDoc]:
        """
        对候选结果进行规则重排。

        说明：
        - 仅在 `distance` / `distance_then_source_timestamp_desc` 排序模式下生效。
        - 其他排序模式直接透传，避免改变调用方显式排序语义。
        - 输出时会写入 `rerank_score`，便于观测和调参。
        """
        if not candidates or top_k <= 0:
            return []
        if sort_by not in {"distance", "distance_then_source_timestamp_desc"}:
            return candidates[:top_k]

        query_tokens = self._tokenize_query(query)
        max_keyword_score = max((doc.keyword_score or 0.0) for doc in candidates)

        ts_values = [source_timestamp_to_epoch(doc.source_timestamp) for doc in candidates]
        valid_ts = [value for value in ts_values if value is not None]
        min_ts = min(valid_ts) if valid_ts else None
        max_ts = max(valid_ts) if valid_ts else None

        ranked: list[ScoredDoc] = []
        for doc in candidates:
            item = ScoredDoc(**doc.__dict__)
            vector_rel = self._vector_relevance(item.distance)
            keyword_rel = self._keyword_relevance(
                item.keyword_score,
                max_keyword_score=max_keyword_score,
            )
            recency_rel = self._recency_relevance(
                item.source_timestamp,
                min_ts=min_ts,
                max_ts=max_ts,
            )
            query_overlap_rel = self._query_overlap_relevance(
                query_tokens=query_tokens,
                text=item.text,
                summary_text=item.summary_text,
            )
            contradiction_penalty = self._contradiction_penalty(
                query_tokens=query_tokens,
                text=item.text,
                summary_text=item.summary_text,
                overlap=query_overlap_rel,
            )
            source_boost = (
                self.config.canonical_fact_boost
                if item.source_type == "memory_fact"
                else 0.0
            )

            rerank_score = (
                self.config.vector_weight * vector_rel
                + self.config.keyword_weight * keyword_rel
                + self.config.recency_weight * recency_rel
                + self.config.query_overlap_weight * query_overlap_rel
                + source_boost
                - contradiction_penalty
            )
            item.rerank_score = float(max(0.0, rerank_score))
            ranked.append(item)

        if sort_by == "distance_then_source_timestamp_desc":
            ranked.sort(
                key=lambda x: (
                    -(x.rerank_score or 0.0),
                    source_timestamp_to_epoch(x.source_timestamp) is None,
                    -(source_timestamp_to_epoch(x.source_timestamp) or 0.0),
                    x.distance if x.distance is not None else 1.0,
                )
            )
        else:
            ranked.sort(
                key=lambda x: (
                    -(x.rerank_score or 0.0),
                    x.distance if x.distance is not None else 1.0,
                )
            )

        return ranked[:top_k]

    def _tokenize_query(self, query: str) -> set[str]:
        tokens = self._analyzer.tokenize(query or "")
        return {token for token in tokens if self._CJK_RE.search(token)}

    @staticmethod
    def _vector_relevance(distance: float | None) -> float:
        if distance is None:
            return 0.0
        d = min(max(float(distance), 0.0), 2.0)
        return 1.0 - (d / 2.0)

    @staticmethod
    def _keyword_relevance(keyword_score: float | None, *, max_keyword_score: float) -> float:
        if max_keyword_score <= 0:
            return 0.0
        return float(keyword_score or 0.0) / max_keyword_score

    @staticmethod
    def _recency_relevance(
        source_timestamp: str | None,
        *,
        min_ts: float | None,
        max_ts: float | None,
    ) -> float:
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
        text: str | None,
        summary_text: str | None,
    ) -> float:
        if not query_tokens:
            return 0.0
        hay = f"{summary_text or ''} {text or ''}".strip()
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
        text: str | None,
        summary_text: str | None,
        overlap: float,
    ) -> float:
        if overlap <= 0 or not query_tokens:
            return 0.0
        hay = f"{summary_text or ''} {text or ''}"
        if not hay:
            return 0.0
        if not any(cue in hay for cue in self._NEGATIVE_CUES):
            return 0.0
        return self.config.contradiction_penalty * (0.5 + 0.5 * overlap)

