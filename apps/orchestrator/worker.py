from __future__ import annotations

import time

from packages.llm.embeddings.factory import create_embedding_provider_from_env
from packages.memory.long_term.ingestion.ingestion_service import MemoryIngestionService
from packages.memory.long_term.lifecycle.embedding_jobs import EmbeddingJobRunner
from packages.memory.long_term.lifecycle.forgetting import MemoryForgettingService
from packages.memory.long_term.lifecycle.rebuild import MemoryRebuildService
from packages.retrieval.chunking.simple_text_chunker import SimpleTextChunker
from packages.storage.postgres.repositories.memory_fact_repository import (
    MemoryFactRepository,
)
from packages.storage.postgres.repositories.memory_repository import MemoryChunkRepository
from packages.storage.postgres.repositories.project_repository import ProjectRepository
from packages.storage.postgres.repositories.chapter_candidate_repository import (
    ChapterCandidateRepository,
)
from packages.storage.postgres.repositories.webhook_delivery_repository import (
    WebhookDeliveryRepository,
)
from packages.storage.postgres.repositories.webhook_subscription_repository import (
    WebhookSubscriptionRepository,
)
from packages.storage.postgres.session import create_session_factory
from packages.webhooks.delivery_runner import WebhookDeliveryRunner
from packages.workflows.orchestration.runtime_config import OrchestratorRuntimeConfig
from packages.workflows.orchestration.service import WritingOrchestratorService


def run_worker_once() -> int:
    cfg = OrchestratorRuntimeConfig.from_env()
    session_factory = create_session_factory()
    db = session_factory()
    try:
        service = WritingOrchestratorService.build_default(db)
        processed = service.process_once(limit=service.runtime_config.worker_batch_size)
        if processed <= 0 and cfg.lifecycle_enabled:
            _run_lifecycle_tick(db=db, cfg=cfg)
        return processed
    finally:
        db.close()


def run_worker_loop() -> None:
    cfg = OrchestratorRuntimeConfig.from_env()
    session_factory = create_session_factory()
    while True:
        db = session_factory()
        try:
            service = WritingOrchestratorService.build_default(db)
            processed = service.process_once(limit=cfg.worker_batch_size)
            if processed <= 0:
                if cfg.lifecycle_enabled:
                    _run_lifecycle_tick(db=db, cfg=cfg)
                time.sleep(cfg.worker_poll_interval_seconds)
        finally:
            db.close()


def _run_lifecycle_tick(*, db, cfg: OrchestratorRuntimeConfig) -> None:
    memory_repo = MemoryChunkRepository(db)
    memory_fact_repo = MemoryFactRepository(db)
    ingestion_service = MemoryIngestionService(
        chunker=SimpleTextChunker(chunk_size=500, chunk_overlap=80),
        embedding_provider=create_embedding_provider_from_env(),
        memory_repo=memory_repo,
        memory_fact_repo=memory_fact_repo,
        embedding_batch_size=8,
        replace_existing_by_default=True,
    )

    # 生命周期任务与主写作链路隔离：任一任务失败不影响 worker 主循环。
    try:
        EmbeddingJobRunner(ingestion_service=ingestion_service).run_once(
            limit=max(1, int(cfg.lifecycle_embedding_limit)),
            continue_on_error=True,
        )
    except Exception:
        pass

    try:
        MemoryRebuildService(
            ingestion_service=ingestion_service,
            memory_repo=memory_repo,
        ).recompute_stale(
            process_limit=max(1, int(cfg.lifecycle_rebuild_limit)),
            continue_on_error=True,
        )
    except Exception:
        pass

    try:
        forgetting_service = MemoryForgettingService(
            memory_repo=memory_repo,
            memory_fact_repo=memory_fact_repo,
        )
        project_repo = ProjectRepository(db)
        for project in project_repo.list_all():
            forgetting_service.run_once(
                project_id=project.id,
                limit=max(1, int(cfg.lifecycle_forget_limit)),
                dry_run=bool(cfg.lifecycle_forget_dry_run),
                allow_hard_delete=False,
            )
    except Exception:
        pass

    try:
        ChapterCandidateRepository(db).expire_pending()
    except Exception:
        pass

    if bool(cfg.webhook_enabled):
        try:
            WebhookDeliveryRunner(
                delivery_repo=WebhookDeliveryRepository(db),
                subscription_repo=WebhookSubscriptionRepository(db),
            ).run_once(limit=max(1, int(cfg.webhook_batch_size)))
        except Exception:
            pass
