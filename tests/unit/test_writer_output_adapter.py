from __future__ import annotations

import unittest

from packages.workflows.writer_output import WriterOutputAdapter, WriterOutputAdapterError


class TestWriterOutputAdapter(unittest.TestCase):
    def test_prefers_chapter_payload(self) -> None:
        payload = {
            "mode": "draft",
            "status": "success",
            "segments": [
                {"beat_id": 1, "content": "短A"},
                {"beat_id": 2, "content": "短B"},
            ],
            "word_count": 12,
            "chapter": {
                "title": "章节标题",
                "content": "完整正文明显长于各分段拼接后的总信息量",
                "summary": "摘要",
            },
        }
        out = WriterOutputAdapter.normalize(payload, mode="draft")
        self.assertEqual(out["chapter"]["title"], "章节标题")
        self.assertEqual(out["chapter"]["content"], "完整正文明显长于各分段拼接后的总信息量")
        self.assertEqual(out["word_count"], 12)

    def test_prefers_segments_when_more_substantive_than_chapter_content(self) -> None:
        """与字数校验口径一致：segments 有效字更多时以 segments 为 chapter 正文。"""
        payload = {
            "mode": "draft",
            "status": "success",
            "segments": [
                {"beat_id": 1, "content": "第一叙事段内容足够长用于压过短chapter"},
                {"beat_id": 2, "content": "第二叙事段继续补足有效字数差距"},
            ],
            "word_count": 0,
            "chapter": {
                "title": "标题",
                "content": "短章",
                "summary": "摘要",
            },
        }
        out = WriterOutputAdapter.normalize(payload, mode="draft")
        self.assertIn("第一叙事段", out["chapter"]["content"])
        self.assertIn("第二叙事段", out["chapter"]["content"])
        self.assertNotEqual(out["chapter"]["content"].strip(), "短章")

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
