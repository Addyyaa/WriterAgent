from packages.retrieval.chunking.base import TextChunker


class SimpleTextChunker(TextChunker):
    _BOUNDARY_CHARS = "。！？!?；;，,\n"

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 80,
        boundary_window: int = 80,
        prefer_sentence_boundary: bool = True,
    ):
        if chunk_size <= 0:
            raise ValueError("chunk_size 必须大于 0")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap 不能小于 0")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap 必须小于 chunk_size")
        if boundary_window < 0:
            raise ValueError("boundary_window 不能小于 0")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.boundary_window = boundary_window
        self.prefer_sentence_boundary = prefer_sentence_boundary

    def chunk(self, text: str) -> list[str]:
        if not text or not text.strip():
            return []

        text = text.strip()
        chunks: list[str] = []

        start = 0
        step = self.chunk_size - self.chunk_overlap

        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            if self.prefer_sentence_boundary and end < len(text):
                adjusted = self._adjust_end_to_boundary(text=text, start=start, end=end)
                if adjusted > start:
                    end = adjusted
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break

            next_start = max(start + 1, end - self.chunk_overlap)
            if next_start <= start:
                next_start = start + step
            start = next_start

        return chunks

    def _adjust_end_to_boundary(self, *, text: str, start: int, end: int) -> int:
        if self.boundary_window == 0:
            return end

        left = max(start + 1, end - self.boundary_window)
        right = min(len(text), end + self.boundary_window)
        window = text[left:right]
        if not window:
            return end

        center = end - left
        best = None
        best_distance = None
        for idx, ch in enumerate(window):
            if ch not in self._BOUNDARY_CHARS:
                continue
            candidate = left + idx + 1
            distance = abs(idx - center)
            if best is None or distance < (best_distance or 10**9):
                best = candidate
                best_distance = distance

        return best or end
