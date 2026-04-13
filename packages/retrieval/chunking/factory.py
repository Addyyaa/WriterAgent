from __future__ import annotations

from packages.retrieval.chunking.base import TextChunker
from packages.retrieval.chunking.markdown_chunker import MarkdownChunker
from packages.retrieval.chunking.recursive_chunker import RecursiveChunker
from packages.retrieval.chunking.semantic_chunker import SemanticChunker
from packages.retrieval.chunking.sentence_chunker import SentenceChunker
from packages.retrieval.chunking.simple_text_chunker import SimpleTextChunker


def create_chunker(kind: str, **kwargs) -> TextChunker:
    normalized = (kind or "simple").strip().lower()
    if normalized in {"simple", "text"}:
        return SimpleTextChunker(**kwargs)
    if normalized in {"sentence", "sent"}:
        return SentenceChunker(**kwargs)
    if normalized in {"semantic", "sem"}:
        return SemanticChunker(**kwargs)
    if normalized in {"markdown", "md"}:
        return MarkdownChunker(**kwargs)
    if normalized in {"recursive", "rec"}:
        return RecursiveChunker(**kwargs)
    raise ValueError(f"未知 chunker 类型: {kind}")
