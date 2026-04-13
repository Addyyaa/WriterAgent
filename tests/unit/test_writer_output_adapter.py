from __future__ import annotations

import unittest

from packages.workflows.writer_output import WriterOutputAdapter, WriterOutputAdapterError


class TestWriterOutputAdapter(unittest.TestCase):
    def test_prefers_chapter_payload(self) -> None:
        payload = {
            "mode": "draft",
            "status": "success",
            "segments": [
                {"beat_id": 1, "content": "段落A"},
                {"beat_id": 2, "content": "段落B"},
            ],
            "word_count": 12,
            "chapter": {
                "title": "章节标题",
                "content": "完整正文",
                "summary": "摘要",
            },
        }
        out = WriterOutputAdapter.normalize(payload, mode="draft")
        self.assertEqual(out["chapter"]["title"], "章节标题")
        self.assertEqual(out["chapter"]["content"], "完整正文")
        self.assertEqual(out["word_count"], 12)

    def test_fallback_to_segments_when_chapter_missing(self) -> None:
        payload = {
            "status": "success",
            "segments": [
                {"beat_id": 1, "content": "第一段"},
                {"beat_id": 2, "content": "第二段"},
            ],
        }
        out = WriterOutputAdapter.normalize(payload, mode="revision")
        self.assertEqual(out["mode"], "revision")
        self.assertIn("第一段", out["chapter"]["content"])
        self.assertTrue(out["chapter"]["summary"])

    def test_raise_when_no_content_available(self) -> None:
        payload = {
            "mode": "draft",
            "status": "success",
            "segments": [],
            "chapter": {"title": "x", "content": "", "summary": ""},
        }
        with self.assertRaises(WriterOutputAdapterError):
            WriterOutputAdapter.normalize(payload, mode="draft")


if __name__ == "__main__":
    unittest.main(verbosity=2)
