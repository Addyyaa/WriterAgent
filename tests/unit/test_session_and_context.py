from __future__ import annotations

import unittest

from packages.memory.short_term.session_memory import SessionMemoryService
from packages.memory.working_memory.context_builder import ContextBuilder


class TestSessionAndContext(unittest.TestCase):
    def test_session_compress(self) -> None:
        service = SessionMemoryService()
        summary = service.compress(
            [
                {"role": "user", "content": "主角在北港钟楼发现了线索。"},
                {"role": "assistant", "content": "线索显示星港协议第七条禁止启动深渊引擎。"},
            ],
            token_budget=200,
        )
        self.assertGreater(len(summary.summary), 0)
        self.assertGreaterEqual(len(summary.key_facts), 1)

    def test_context_builder_budget(self) -> None:
        builder = ContextBuilder()
        package = builder.build(
            query="问：最近发生了什么",
            long_term_rows=[
                {"source_type": "memory_fact", "text": "事件A" * 50, "distance": 0.1},
                {"source_type": "chapter", "text": "事件B" * 50, "distance": 0.2},
            ],
            session_summary=None,
            token_budget=80,
        )
        self.assertLessEqual(package.used_tokens, package.token_budget)
        self.assertGreaterEqual(len(package.items), 1)

    def test_context_builder_prefers_summary_when_budget_tight(self) -> None:
        builder = ContextBuilder()
        original = (
            "主角在北港钟楼下解析星港协议，确认第七条涉及深渊引擎禁令。"
            "随后与港务官发生冲突，并拿到旧航海日志。"
        ) * 8
        package = builder.build(
            query="深渊引擎禁令",
            long_term_rows=[
                {
                    "source_type": "memory_fact",
                    "text": original,
                    "summary_text": "北港钟楼线索确认第七条禁令与深渊引擎相关。",
                    "distance": 0.1,
                }
            ],
            session_summary=None,
            token_budget=48,
        )
        self.assertEqual(len(package.items), 1)
        self.assertLess(len(package.items[0].text), len(original))
        self.assertLessEqual(package.used_tokens, package.token_budget)


if __name__ == "__main__":
    unittest.main(verbosity=2)
