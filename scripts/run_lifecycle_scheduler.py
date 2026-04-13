from __future__ import annotations

import argparse
import json
from uuid import UUID

from packages.llm.embeddings.factory import create_embedding_provider_from_env
from packages.memory.long_term.ingestion.ingestion_service import MemoryIngestionService
from packages.memory.long_term.lifecycle.embedding_jobs import EmbeddingJobRunner
from packages.memory.long_term.lifecycle.forgetting import MemoryForgettingService
from packages.memory.long_term.lifecycle.rebuild import MemoryRebuildService
from packages.retrieval.chunking.factory import create_chunker
from packages.retrieval.indexers.chapter_indexer import ChapterIndexer
from packages.retrieval.indexers.memory_indexer import MemoryIndexer
from packages.retrieval.indexers.scheduler import IndexScheduler
from packages.retrieval.indexers.world_entry_indexer import WorldEntryIndexer
from packages.storage.postgres.repositories.memory_fact_repository import (
    MemoryFactRepository,
)
from packages.storage.postgres.repositories.memory_repository import MemoryChunkRepository
from packages.storage.postgres.session import create_session_factory


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run lifecycle + index scheduler")
    parser.add_argument("--project-id", type=str, default=None)
    parser.add_argument("--embedding-limit", type=int, default=200)
    parser.add_argument("--rebuild-process-limit", type=int, default=200)
    parser.add_argument("--forget-limit", type=int, default=200)
    parser.add_argument("--forget-apply", action="store_true")
    parser.add_argument("--index-mode", choices=["full", "incremental"], default="incremental")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    project_id = UUID(args.project_id) if args.project_id else None
    session_factory = create_session_factory()
    db = session_factory()
    try:
        memory_repo = MemoryChunkRepository(db)
        memory_fact_repo = MemoryFactRepository(db)

        ingestion = MemoryIngestionService(
            chunker=create_chunker("simple", chunk_size=500, chunk_overlap=80),
            embedding_provider=create_embedding_provider_from_env(),
            memory_repo=memory_repo,
            memory_fact_repo=memory_fact_repo,
            embedding_batch_size=8,
            replace_existing_by_default=True,
        )

        embedding_runner = EmbeddingJobRunner(ingestion_service=ingestion)
        rebuild_service = MemoryRebuildService(
            ingestion_service=ingestion,
            memory_repo=memory_repo,
        )
        forgetting_service = MemoryForgettingService(
            memory_repo=memory_repo,
            memory_fact_repo=memory_fact_repo,
        )

        emb_report = embedding_runner.run_once(
            project_id=project_id,
            limit=args.embedding_limit,
            continue_on_error=True,
        )
        rebuild_report = rebuild_service.recompute_stale(
            project_id=project_id,
            process_limit=args.rebuild_process_limit,
            continue_on_error=True,
        )
        forget_report = None
        if project_id is not None:
            forget_report = forgetting_service.run_once(
                project_id=project_id,
                limit=args.forget_limit,
                dry_run=not bool(args.forget_apply),
                allow_hard_delete=False,
            )

        scheduler = IndexScheduler()
        scheduler.register(ChapterIndexer())
        scheduler.register(MemoryIndexer())
        scheduler.register(WorldEntryIndexer())
        if args.index_mode == "full":
            index_report = scheduler.run_full()
        else:
            index_report = scheduler.run_incremental()

        print(
            json.dumps(
                {
                    "embedding": emb_report.__dict__,
                    "rebuild": rebuild_report.__dict__,
                    "forgetting": forget_report.__dict__ if forget_report is not None else None,
                    "index": index_report.__dict__,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
