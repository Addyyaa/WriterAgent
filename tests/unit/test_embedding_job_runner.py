from __future__ import annotations

import unittest

from packages.memory.long_term.ingestion.ingestion_service import PendingEmbeddingProcessStats
from packages.memory.long_term.lifecycle.embedding_jobs import EmbeddingJobRunner


class _FakeIngestionService:
    def process_pending_embeddings(self, **kwargs) -> PendingEmbeddingProcessStats:
        del kwargs
        return PendingEmbeddingProcessStats(
            requested=10,
            processed=8,
            failed=1,
            skipped=1,
            retried=2,
            recovered_processing=1,
        )


class _FakeJobRunRow:
    def __init__(self, row_id: str) -> None:
        self.id = row_id


class _FakeJobRunRepo:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create_run(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeJobRunRow(f"run-{len(self.calls)}")


class TestEmbeddingJobRunner(unittest.TestCase):
    def test_run_once(self) -> None:
        repo = _FakeJobRunRepo()
        runner = EmbeddingJobRunner(
            ingestion_service=_FakeIngestionService(),
            job_run_repo=repo,
        )
        result = runner.run_once(limit=50)
        self.assertEqual(result.requested, 10)
        self.assertEqual(result.processed, 8)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.run_id, "run-1")
        self.assertGreaterEqual(result.duration_seconds, 0.0)
        self.assertEqual(len(repo.calls), 1)

    def test_run_loop_with_max_runs(self) -> None:
        runner = EmbeddingJobRunner(ingestion_service=_FakeIngestionService())
        reports = runner.run_loop(max_runs=2, interval_seconds=0)
        self.assertEqual(len(reports), 2)
        self.assertTrue(all(item.status == "partial" for item in reports))


if __name__ == "__main__":
    unittest.main(verbosity=2)
