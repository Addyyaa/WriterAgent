from __future__ import annotations

import math
from collections import Counter

from packages.retrieval.keyword.analyzer import SimpleAnalyzer
from packages.retrieval.keyword.base import KeywordRetriever


class BM25Retriever(KeywordRetriever):
    def __init__(self, k1: float = 1.5, b: float = 0.75, analyzer: SimpleAnalyzer | None = None) -> None:
        self.k1 = k1
        self.b = b
        self.analyzer = analyzer or SimpleAnalyzer()
        self.docs: list[list[str]] = []
        self.doc_freq: Counter[str] = Counter()
        self.avg_doc_len: float = 0.0

    def index(self, docs: list[str]) -> None:
        self.docs = [self.analyzer.tokenize(doc) for doc in docs]
        self.doc_freq = Counter()
        for tokens in self.docs:
            for token in set(tokens):
                self.doc_freq[token] += 1
        total_len = sum(len(tokens) for tokens in self.docs)
        self.avg_doc_len = (total_len / len(self.docs)) if self.docs else 0.0

    def search(self, query: str, top_k: int = 5) -> list[tuple[int, float]]:
        if top_k <= 0:
            return []
        q_tokens = self.analyzer.tokenize(query)
        if not q_tokens or not self.docs:
            return []

        scores: list[tuple[int, float]] = []
        n_docs = len(self.docs)

        for idx, tokens in enumerate(self.docs):
            if not tokens:
                continue
            tf = Counter(tokens)
            score = 0.0
            doc_len = len(tokens)
            for term in q_tokens:
                if term not in tf:
                    continue
                df = self.doc_freq.get(term, 0)
                idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
                numerator = tf[term] * (self.k1 + 1)
                denominator = tf[term] + self.k1 * (
                    1 - self.b + self.b * (doc_len / max(self.avg_doc_len, 1e-6))
                )
                score += idf * (numerator / denominator)
            if score > 0:
                scores.append((idx, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]
