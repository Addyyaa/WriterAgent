from __future__ import annotations

import unittest

from packages.retrieval.chunking.simple_text_chunker import SimpleTextChunker


class TestSimpleTextChunker(unittest.TestCase):
    def test_overlap_and_boundary(self) -> None:
        text = (
            "第一段在北港钟楼发现线索。"
            "第二段确认第七条禁令。"
            "第三段主角记录航海日志。"
            "第四段准备夜间潜入。"
        )
        chunker = SimpleTextChunker(
            chunk_size=26,
            chunk_overlap=6,
            boundary_window=10,
            prefer_sentence_boundary=True,
        )
        chunks = chunker.chunk(text)

        self.assertGreaterEqual(len(chunks), 2)
        for chunk in chunks:
            self.assertTrue(chunk.strip())
            self.assertLessEqual(len(chunk), 36)


if __name__ == "__main__":
    unittest.main(verbosity=2)
