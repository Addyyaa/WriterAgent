from __future__ import annotations

from packages.retrieval.chunking.base import TextChunker


class RecursiveChunker(TextChunker):
    """递归分块：按段落/句子/字符逐级切分。"""

    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 120) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size 必须大于 0")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap 不能小于 0")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap 必须小于 chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk(self, text: str) -> list[str]:
        if not text or not text.strip():
            return []
        text = text.strip()

        paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
        if not paragraphs:
            return []

        out: list[str] = []
        for paragraph in paragraphs:
            if len(paragraph) <= self.chunk_size:
                out.append(paragraph)
                continue

            # 先按句子切
            sentences = self._split_sentences(paragraph)
            sentence_buf = ""
            for sentence in sentences:
                candidate = (sentence_buf + sentence).strip()
                if len(candidate) <= self.chunk_size:
                    sentence_buf = candidate
                    continue
                if sentence_buf:
                    out.append(sentence_buf)
                sentence_buf = sentence
            if sentence_buf:
                out.append(sentence_buf)

        # 再做 overlap 合并，保持上下文连续。
        return self._with_overlap(out)

    def _with_overlap(self, chunks: list[str]) -> list[str]:
        if not chunks:
            return []
        out: list[str] = []
        for idx, chunk in enumerate(chunks):
            if idx == 0 or self.chunk_overlap == 0:
                out.append(chunk)
                continue
            prev_tail = chunks[idx - 1][-self.chunk_overlap :]
            out.append((prev_tail + chunk).strip())
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
