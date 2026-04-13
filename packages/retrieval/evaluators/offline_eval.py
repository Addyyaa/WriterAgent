from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from packages.retrieval.evaluators.dataset import EvalDataset
from packages.retrieval.evaluators.metrics import mrr, ndcg_at_k, recall_at_k


RetrieverFn = Callable[[str, dict | None, int], list[str]]


@dataclass(frozen=True)
class OfflineEvalReport:
    dataset_name: str
    total_samples: int
    recall_at_k: float
    mrr: float
    ndcg_at_k: float


class OfflineEvaluator:
    """离线检索评测器。"""

    def evaluate(
        self,
        *,
        dataset: EvalDataset,
        retriever: RetrieverFn,
        k: int = 5,
    ) -> OfflineEvalReport:
        if k <= 0:
            raise ValueError("k 必须大于 0")

        recall_scores: list[float] = []
        mrr_scores: list[float] = []
        ndcg_scores: list[float] = []

        for sample in dataset.samples:
            results = retriever(sample.query, sample.filters, k)
            hits = [1 if item in set(sample.positives) else 0 for item in results[:k]]

            recall_scores.append(recall_at_k(hits, k))
            mrr_scores.append(mrr(hits, k))
            ndcg_scores.append(ndcg_at_k(hits, k))

        total = len(dataset.samples)
        if total == 0:
            return OfflineEvalReport(
                dataset_name=dataset.name,
                total_samples=0,
                recall_at_k=0.0,
                mrr=0.0,
                ndcg_at_k=0.0,
            )

        return OfflineEvalReport(
            dataset_name=dataset.name,
            total_samples=total,
            recall_at_k=sum(recall_scores) / total,
            mrr=sum(mrr_scores) / total,
            ndcg_at_k=sum(ndcg_scores) / total,
        )
