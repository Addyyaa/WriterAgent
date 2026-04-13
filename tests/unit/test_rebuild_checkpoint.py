from __future__ import annotations

import unittest

from packages.memory.long_term.lifecycle.rebuild import MemoryRebuildService


class _FakeIngestionService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def ingest_text(self, **kwargs):
        self.calls.append(kwargs)
        return [{"id": len(self.calls)}]

    def process_pending_embeddings(self, **kwargs):
        del kwargs
        raise RuntimeError("not used")


class _FakeMemoryRepo:
    def list_by_source(self, **kwargs):
        del kwargs
        return []

    def mark_embedding_stale(self, _id):
        return None

    def reset_stale_to_pending(self, **kwargs):
        del kwargs
        return 0


class _State:
    def __init__(self, next_index: int = 0, status: str = "running", metadata_json: dict | None = None):
        self.next_index = next_index
        self.status = status
        self.metadata_json = metadata_json or {}


class _FakeCheckpointRepo:
    def __init__(self) -> None:
        self.state: dict[tuple[str, str], _State] = {}

    def get_checkpoint(self, *, job_key: str, project_id):
        return self.state.get((job_key, str(project_id)))

    def save_checkpoint(self, *, job_key: str, project_id, next_index: int, status: str, metadata_json: dict):
        item = _State(next_index=next_index, status=status, metadata_json=metadata_json)
        self.state[(job_key, str(project_id))] = item
        return item


class TestMemoryRebuildCheckpoint(unittest.TestCase):
    def test_resume_from_persisted_checkpoint(self) -> None:
        ingestion = _FakeIngestionService()
        checkpoint_repo = _FakeCheckpointRepo()
        project_id = "p1"
        checkpoint_repo.save_checkpoint(
            job_key="job",
            project_id=project_id,
            next_index=1,
            status="running",
            metadata_json={},
        )

        svc = MemoryRebuildService(
            ingestion_service=ingestion,
            memory_repo=_FakeMemoryRepo(),
            checkpoint_repo=checkpoint_repo,
        )
        next_idx, rebuilt = svc.rebuild_with_checkpoint(
            project_id=project_id,
            job_key="job",
            sources=[
                {"source_type": "a", "text": "skip"},
                {"source_type": "b", "text": "one"},
                {"source_type": "c", "text": "two"},
            ],
        )
        self.assertEqual(next_idx, 3)
        self.assertEqual(rebuilt, 2)
        self.assertEqual(len(ingestion.calls), 2)
        state = checkpoint_repo.get_checkpoint(job_key="job", project_id=project_id)
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.status, "done")
        self.assertEqual(state.next_index, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)

