from __future__ import annotations

from packages.retrieval.chunking.base import TextChunker


class MarkdownChunker(TextChunker):
    def __init__(self, max_chars_per_chunk: int = 1200) -> None:
        if max_chars_per_chunk <= 0:
            raise ValueError("max_chars_per_chunk 必须大于 0")
        self.max_chars_per_chunk = max_chars_per_chunk

    def chunk(self, text: str) -> list[str]:
        if not text or not text.strip():
            return []

        sections = self._split_sections(text)
        out: list[str] = []
        buff = ""
        for section in sections:
            if len(section) > self.max_chars_per_chunk:
                if buff.strip():
                    out.append(buff.strip())
                    buff = ""
                for i in range(0, len(section), self.max_chars_per_chunk):
                    part = section[i : i + self.max_chars_per_chunk].strip()
                    if part:
                        out.append(part)
                continue

            candidate = (buff + "\n\n" + section).strip() if buff else section
            if len(candidate) > self.max_chars_per_chunk:
                if buff.strip():
                    out.append(buff.strip())
                buff = section
            else:
                buff = candidate

        if buff.strip():
            out.append(buff.strip())
        return out

    @staticmethod
    def _split_sections(text: str) -> list[str]:
        sections: list[str] = []
        current = ""
        for line in text.splitlines():
            if line.lstrip().startswith("#") and current.strip():
                sections.append(current.strip())
                current = line
            else:
                current = f"{current}\n{line}" if current else line
        if current.strip():
            sections.append(current.strip())
        return sections
