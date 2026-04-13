from __future__ import annotations

import builtins
import unittest
from unittest import mock

from packages.retrieval.config import RetrievalRuntimeConfig, VectorBackendRuntimeConfig
from packages.retrieval.errors import RetrievalConfigError, RetrieverUnavailableError
from packages.retrieval.vector.factory import create_vector_store
from packages.retrieval.vector.pgvector_store import PgVectorStore


class _FakeMemoryRepo:
    def __init__(self) -> None:
        self.last_search = None

    def delete(self, _chunk_id):
        return False

    def get(self, _chunk_id):
        return None

    def create_chunks(self, project_id, chunks):
        return [{"project_id": project_id, "chunks": chunks}]

    def update_chunk(self, chunk_id, **payload):
        return {"id": chunk_id, **payload}

    def similarity_search(self, **kwargs):
        self.last_search = kwargs
        return [{"id": "1", "text": "demo", "distance": 0.1}]


class TestVectorStoreFactory(unittest.TestCase):
    def test_default_pgvector(self) -> None:
        cfg = RetrievalRuntimeConfig()
        store = create_vector_store(memory_repo=_FakeMemoryRepo(), runtime_config=cfg)
        self.assertIsInstance(store, PgVectorStore)

    def test_invalid_backend(self) -> None:
        cfg = RetrievalRuntimeConfig(
            vector=VectorBackendRuntimeConfig(backend="unknown")
        )
        with self.assertRaises(RetrievalConfigError):
            create_vector_store(memory_repo=_FakeMemoryRepo(), runtime_config=cfg)

    def test_faiss_missing_dependency_raises(self) -> None:
        cfg = RetrievalRuntimeConfig(
            vector=VectorBackendRuntimeConfig(
                backend="faiss",
                dimension=8,
            )
        )
        original_import = builtins.__import__

        def _import(name, globals=None, locals=None, fromlist=(), level=0):
            if name in {"faiss", "numpy"}:
                raise ImportError("missing optional dependency")
            return original_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=_import):
            with self.assertRaises(RetrieverUnavailableError):
                create_vector_store(memory_repo=_FakeMemoryRepo(), runtime_config=cfg)


if __name__ == "__main__":
    unittest.main(verbosity=2)

