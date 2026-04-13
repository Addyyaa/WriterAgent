from __future__ import annotations

from packages.retrieval.chunking.base import TextChunker


class SentenceChunker(TextChunker):
    def __init__(self, max_sentences_per_chunk: int = 6) -> None:
        if max_sentences_per_chunk <= 0:
            raise ValueError("max_sentences_per_chunk 必须大于 0")
        self.max_sentences_per_chunk = max_sentences_per_chunk

    def chunk(self, text: str) -> list[str]:
        if not text or not text.strip():
            return []
        sentences = self._split_sentences(text.strip())
        out: list[str] = []
        for i in range(0, len(sentences), self.max_sentences_per_chunk):
            part = "".join(sentences[i : i + self.max_sentences_per_chunk]).strip()
            if part:
                out.append(part)
        return out

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        out: list[str] = []
        buff = ""
        for ch in text:
            buff += ch
            if ch in {"。", "！", "？", ".", "!", "?", "\n"}:
                segment = buff.strip()
                if segment:
                    out.append(segment)
                buff = ""
        if buff.strip():
            out.append(buff.strip())
        return out
