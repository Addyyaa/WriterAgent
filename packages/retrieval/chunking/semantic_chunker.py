from __future__ import annotations

from packages.retrieval.chunking.base import TextChunker
from packages.retrieval.chunking.sentence_chunker import SentenceChunker


class SemanticChunker(TextChunker):
    """语义分块轻量实现。

    当前版本采用句子分块并按长度聚合，保留后续接入 embedding 边界检测的接口位置。
    """

    def __init__(self, max_chars_per_chunk: int = 1000) -> None:
        if max_chars_per_chunk <= 0:
            raise ValueError("max_chars_per_chunk 必须大于 0")
        self.max_chars_per_chunk = max_chars_per_chunk
        self.sentence_chunker = SentenceChunker(max_sentences_per_chunk=1)

    def chunk(self, text: str) -> list[str]:
        sentences = self.sentence_chunker.chunk(text)
        if not sentences:
            return []

        out: list[str] = []
        buff = ""
        for sentence in sentences:
            candidate = (buff + sentence).strip()
            if len(candidate) <= self.max_chars_per_chunk:
                buff = candidate
                continue
            if buff:
                out.append(buff)
            buff = sentence
        if buff:
            out.append(buff)
        return out
