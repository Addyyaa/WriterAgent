from __future__ import annotations

import os
import unittest
from unittest import mock

from packages.memory.long_term.runtime_config import MemoryRuntimeConfig
from packages.retrieval.config import RetrievalRuntimeConfig


class TestRuntimeConfigCompat(unittest.TestCase):
    @mock.patch.dict(
        os.environ,
        {
            "WRITER_RETRIEVAL_TOP_K": "9",
            "WRITER_RETRIEVAL_AB_TEST_B_RATIO": "2.0",
            "WRITER_MEMORY_INGEST_EMBEDDING_BATCH_SIZE": "16",
            "WRITER_MEMORY_ENABLE_LOGGING": "false",
        },
        clear=False,
    )
    def test_runtime_from_env_keeps_behavior(self) -> None:
        retrieval = RetrievalRuntimeConfig.from_env()
        memory = MemoryRuntimeConfig.from_env()

        self.assertEqual(retrieval.top_k, 9)
        self.assertAlmostEqual(retrieval.rerank.ab_test.b_ratio, 1.0, places=6)
        self.assertEqual(memory.ingestion.embedding_batch_size, 16)
        self.assertFalse(memory.observability.enable_logging)


if __name__ == "__main__":
    unittest.main(verbosity=2)
