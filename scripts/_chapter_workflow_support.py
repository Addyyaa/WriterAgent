from __future__ import annotations

import hashlib
import math

from sqlalchemy.orm import Session

from packages.llm.embeddings.base import EmbeddingProvider
from packages.llm.text_generation.base import TextGenerationProvider
from packages.llm.text_generation.mock_provider import MockTextGenerationProvider
from packages.memory.long_term.ingestion.ingestion_service import MemoryIngestionService
from packages.memory.long_term.search.search_service import MemorySearchService
from packages.memory.project_memory.project_memory_service import ProjectMemoryService
from packages.retrieval.chunking.simple_text_chunker import SimpleTextChunker
from packages.storage.postgres.repositories.agent_run_repository import AgentRunRepository
from packages.storage.postgres.repositories.chapter_repository import ChapterRepository
from packages.storage.postgres.repositories.memory_fact_repository import (
    MemoryFactRepository,
)
from packages.storage.postgres.repositories.memory_repository import MemoryChunkRepository
from packages.storage.postgres.repositories.project_repository import ProjectRepository
from packages.storage.postgres.repositories.skill_run_repository import SkillRunRepository
from packages.storage.postgres.repositories.tool_call_repository import ToolCallRepository
from packages.storage.postgres.vector_settings import MEMORY_EMBEDDING_DIM
from packages.workflows.chapter_generation.context_provider import (
    SQLAlchemyStoryContextProvider,
)
from packages.workflows.chapter_generation.service import ChapterGenerationWorkflowService


class DeterministicEmbeddingProvider(EmbeddingProvider):
    @staticmethod
    def _embed_one(text: str) -> list[float]:
        digest = hashlib.sha256((text or "").strip().encode("utf-8")).digest()
        vec = [0.0] * MEMORY_EMBEDDING_DIM
        for i in range(MEMORY_EMBEDDING_DIM):
            vec[i] = (digest[i % len(digest)] / 255.0) - 0.5
        norm = math.sqrt(sum(item * item for item in vec)) or 1.0
        return [item / norm for item in vec]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)


def build_test_chapter_workflow(db: Session) -> ChapterGenerationWorkflowService:
    return build_test_chapter_workflow_with_overrides(db)


def build_test_chapter_workflow_with_overrides(
    db: Session,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    text_provider: TextGenerationProvider | None = None,
    ingestion_service: MemoryIngestionService | None = None,
) -> ChapterGenerationWorkflowService:
    effective_embedding_provider = embedding_provider or DeterministicEmbeddingProvider()
    memory_repo = MemoryChunkRepository(db)
    memory_fact_repo = MemoryFactRepository(db)
    effective_ingestion_service = ingestion_service or MemoryIngestionService(
        chunker=SimpleTextChunker(chunk_size=500, chunk_overlap=80),
        embedding_provider=effective_embedding_provider,
        memory_repo=memory_repo,
        memory_fact_repo=memory_fact_repo,
        embedding_batch_size=8,
        replace_existing_by_default=True,
    )
    search_service = MemorySearchService(
        embedding_provider=effective_embedding_provider,
        memory_repo=memory_repo,
    )
    project_memory_service = ProjectMemoryService(long_term_search=search_service)

    return ChapterGenerationWorkflowService(
        project_repo=ProjectRepository(db),
        chapter_repo=ChapterRepository(db),
        agent_run_repo=AgentRunRepository(db),
        tool_call_repo=ToolCallRepository(db),
        skill_run_repo=SkillRunRepository(db),
        story_context_provider=SQLAlchemyStoryContextProvider(db),
        project_memory_service=project_memory_service,
        ingestion_service=effective_ingestion_service,
        text_provider=text_provider or MockTextGenerationProvider(),
    )
