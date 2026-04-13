from __future__ import annotations

import argparse
import json

from packages.memory.long_term.search.search_service import MemorySearchService
from packages.retrieval.evaluators.dataset import build_dataset
from packages.retrieval.evaluators.offline_eval import OfflineEvaluator
from packages.storage.postgres.repositories.memory_repository import MemoryChunkRepository
from packages.storage.postgres.session import create_session_factory
from packages.llm.embeddings.factory import create_embedding_provider_from_env


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run offline retrieval evaluation")
    parser.add_argument("--dataset", required=True, help="JSON 文件路径")
    parser.add_argument("--k", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    session_factory = create_session_factory()
    db = session_factory()
    try:
        service = MemorySearchService(
            embedding_provider=create_embedding_provider_from_env(),
            memory_repo=MemoryChunkRepository(db),
        )
        dataset = build_dataset(args.dataset)

        def retriever(query: str, filters: dict | None, k: int) -> list[str]:
            f = filters or {}
            rows = service.search_with_scores(
                project_id=f.get("project_id"),
                query=query,
                top_k=k,
                source_type=f.get("source_type"),
                chunk_type=f.get("chunk_type"),
            )
            return [str(item.get("id")) for item in rows]

        report = OfflineEvaluator().evaluate(dataset=dataset, retriever=retriever, k=args.k)
        print(json.dumps(report.__dict__, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
