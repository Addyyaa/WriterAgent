from __future__ import annotations

import math
from collections import Counter

from packages.retrieval.keyword.analyzer import SimpleAnalyzer
from packages.retrieval.keyword.base import KeywordRetriever


class TFIDFRetriever(KeywordRetriever):
    def __init__(self, analyzer: SimpleAnalyzer | None = None) -> None:
        self.analyzer = analyzer or SimpleAnalyzer()
        self.docs: list[list[str]] = []
        self.doc_freq: Counter[str] = Counter()

    def index(self, docs: list[str]) -> None:
        self.docs = [self.analyzer.tokenize(doc) for doc in docs]
        self.doc_freq = Counter()
        for tokens in self.docs:
            for token in set(tokens):
                self.doc_freq[token] += 1

    def search(self, query: str, top_k: int = 5) -> list[tuple[int, float]]:
        if top_k <= 0:
            return []
        q_tokens = self.analyzer.tokenize(query)
        if not q_tokens or not self.docs:
            return []

        n_docs = len(self.docs)
        q_tf = Counter(q_tokens)
        scores: list[tuple[int, float]] = []

        for idx, tokens in enumerate(self.docs):
            tf = Counter(tokens)
            score = 0.0
            for term, q_count in q_tf.items():
                if term not in tf:
                    continue
                df = self.doc_freq.get(term, 0)
                idf = math.log((n_docs + 1) / (df + 1)) + 1.0
                score += float(tf[term]) * float(q_count) * idf
            if score > 0.0:
                scores.append((idx, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


TfIdfRetriever = TFIDFRetriever
