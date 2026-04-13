from __future__ import annotations

import unittest

from packages.memory.project_memory.project_memory_service import ProjectMemoryService


class _FakeSearchService:
    def search_with_scores(self, **kwargs):
        del kwargs
        return [
            {
                "source_type": "memory_fact",
                "text": "联邦协议第七条禁止启动深渊引擎。",
                "distance": 0.1,
                "hybrid_score": 0.4,
                "rerank_score": 0.8,
            }
        ]


class TestProjectMemoryService(unittest.TestCase):
    def test_build_context(self) -> None:
        service = ProjectMemoryService(long_term_search=_FakeSearchService())
        package = service.build_context(
            project_id="p1",
            query="违反联邦协议会有什么后果",
            token_budget=300,
            chat_turns=[{"role": "user", "content": "之前提到过处罚问题"}],
        )
        self.assertGreaterEqual(len(package.items), 1)
        self.assertLessEqual(package.used_tokens, package.token_budget)


if __name__ == "__main__":
    unittest.main(verbosity=2)
