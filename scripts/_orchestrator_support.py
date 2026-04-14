from __future__ import annotations

from pathlib import Path

from packages.evaluation.service import OnlineEvaluationService
from sqlalchemy.orm import Session

from packages.llm.text_generation.factory import create_text_generation_provider
from packages.memory.long_term.ingestion.ingestion_service import MemoryIngestionService
from packages.memory.long_term.search.search_service import MemorySearchService
from packages.memory.project_memory.project_memory_service import ProjectMemoryService
from packages.retrieval.chunking.simple_text_chunker import SimpleTextChunker
from packages.storage.postgres.repositories.agent_message_repository import (
    AgentMessageRepository,
)
from packages.storage.postgres.repositories.agent_run_repository import AgentRunRepository
from packages.storage.postgres.repositories.chapter_repository import ChapterRepository
from packages.storage.postgres.repositories.chapter_candidate_repository import (
    ChapterCandidateRepository,
)
from packages.storage.postgres.repositories.consistency_report_repository import (
    ConsistencyReportRepository,
)
from packages.storage.postgres.repositories.evaluation_repository import (
    EvaluationRepository,
)
from packages.storage.postgres.repositories.memory_fact_repository import (
    MemoryFactRepository,
)
from packages.storage.postgres.repositories.memory_repository import MemoryChunkRepository
from packages.storage.postgres.repositories.outline_repository import OutlineRepository
from packages.storage.postgres.repositories.project_repository import ProjectRepository
from packages.storage.postgres.repositories.retrieval_trace_repository import (
    RetrievalTraceRepository,
)
from packages.storage.postgres.repositories.skill_run_repository import SkillRunRepository
from packages.storage.postgres.repositories.tool_call_repository import ToolCallRepository
from packages.storage.postgres.repositories.user_repository import UserRepository
from packages.storage.postgres.repositories.workflow_run_repository import (
    WorkflowRunRepository,
)
from packages.storage.postgres.repositories.workflow_step_repository import (
    WorkflowStepRepository,
)
from packages.schemas import SchemaRegistry
from packages.skills import SkillRegistry, SkillRuntimeEngine
from packages.tools.chapter_tools.chapter_generation_tool import ChapterGenerationTool
from packages.workflows.chapter_generation.context_provider import (
    SQLAlchemyStoryContextProvider,
)
from packages.workflows.chapter_generation.service import ChapterGenerationWorkflowService
from packages.workflows.consistency_review.service import ConsistencyReviewWorkflowService
from packages.workflows.orchestration.agent_registry import AgentRegistry
from packages.workflows.orchestration.planner import MockDynamicPlanner
from packages.workflows.orchestration.retrieval_loop import RetrievalLoopService
from packages.workflows.orchestration.runtime_config import OrchestratorRuntimeConfig
from packages.workflows.orchestration.service import WritingOrchestratorService
from packages.workflows.outline_generation.service import OutlineGenerationWorkflowService
from packages.workflows.revision.service import RevisionWorkflowService
from scripts._chapter_workflow_support import DeterministicEmbeddingProvider


def build_test_orchestrator_service(db: Session) -> WritingOrchestratorService:
    embedding_provider = DeterministicEmbeddingProvider()
    text_provider = create_text_generation_provider()

    memory_repo = MemoryChunkRepository(db)
    memory_fact_repo = MemoryFactRepository(db)
    ingestion_service = MemoryIngestionService(
        chunker=SimpleTextChunker(chunk_size=500, chunk_overlap=80),
        embedding_provider=embedding_provider,
        memory_repo=memory_repo,
        memory_fact_repo=memory_fact_repo,
        embedding_batch_size=8,
        replace_existing_by_default=True,
    )
    search_service = MemorySearchService(
        embedding_provider=embedding_provider,
        memory_repo=memory_repo,
    )
    project_memory_service = ProjectMemoryService(long_term_search=search_service)

    project_repo = ProjectRepository(db)
    outline_repo = OutlineRepository(db)
    user_repo = UserRepository(db)
    chapter_repo = ChapterRepository(db)
    context_provider = SQLAlchemyStoryContextProvider(db)

    chapter_service = ChapterGenerationWorkflowService(
        project_repo=project_repo,
        chapter_repo=chapter_repo,
        agent_run_repo=AgentRunRepository(db),
        tool_call_repo=ToolCallRepository(db),
        skill_run_repo=SkillRunRepository(db),
        story_context_provider=context_provider,
        project_memory_service=project_memory_service,
        ingestion_service=ingestion_service,
        text_provider=text_provider,
    )

    outline_service = OutlineGenerationWorkflowService(
        project_repo=project_repo,
        outline_repo=outline_repo,
        text_provider=text_provider,
    )

    consistency_service = ConsistencyReviewWorkflowService(
        chapter_repo=chapter_repo,
        report_repo=ConsistencyReportRepository(db),
        story_context_provider=context_provider,
        text_provider=text_provider,
    )

    revision_service = RevisionWorkflowService(
        chapter_repo=chapter_repo,
        report_repo=ConsistencyReportRepository(db),
        ingestion_service=ingestion_service,
        text_provider=text_provider,
    )

    root = Path(__file__).resolve().parents[1]
    schema_registry = SchemaRegistry(root / "packages/schemas")
    skill_registry = SkillRegistry(
        root=root / "packages/skills",
        schema_registry=schema_registry,
        strict=True,
        degrade_mode=False,
    )
    agent_registry = AgentRegistry(
        root=root / "apps/agents",
        schema_registry=schema_registry,
        skill_registry=skill_registry,
        strict=True,
        degrade_mode=False,
    )
    skill_runtime = SkillRuntimeEngine()
    chapter_service.agent_registry = agent_registry
    chapter_service.schema_registry = schema_registry
    chapter_service.skill_runtime = skill_runtime
    revision_service.agent_registry = agent_registry
    revision_service.schema_registry = schema_registry
    revision_service.skill_runtime = skill_runtime
    retrieval_trace_repo = RetrievalTraceRepository(db)
    retrieval_loop = RetrievalLoopService(
        runtime_config=OrchestratorRuntimeConfig(
            worker_poll_interval_seconds=0.1,
            worker_batch_size=3,
            max_step_seconds=120,
            default_max_retries=1,
            default_retry_delay_seconds=1,
            enable_auto_worker=False,
            schema_strict=True,
            schema_degrade_mode=False,
            retrieval_max_rounds=20,
            retrieval_round_top_k=8,
            retrieval_max_unique_evidence=64,
            retrieval_stop_min_coverage=0.85,
            retrieval_stop_min_gain=0.05,
            retrieval_stop_stale_rounds=2,
            workflow_run_timeout_seconds=480,
            context_chapter_window_before=2,
            context_chapter_window_after=1,
            api_v1_enabled=False,
        ),
        project_memory_service=project_memory_service,
        story_context_provider=context_provider,
        project_repo=project_repo,
        outline_repo=outline_repo,
        user_repo=user_repo,
        retrieval_trace_repo=retrieval_trace_repo,
    )

    return WritingOrchestratorService(
        runtime_config=OrchestratorRuntimeConfig(
            worker_poll_interval_seconds=0.1,
            worker_batch_size=3,
            max_step_seconds=120,
            default_max_retries=1,
            default_retry_delay_seconds=1,
            enable_auto_worker=False,
            schema_strict=True,
            schema_degrade_mode=False,
            retrieval_max_rounds=20,
            retrieval_round_top_k=8,
            retrieval_max_unique_evidence=64,
            retrieval_stop_min_coverage=0.85,
            retrieval_stop_min_gain=0.05,
            retrieval_stop_stale_rounds=2,
            workflow_run_timeout_seconds=480,
            context_chapter_window_before=2,
            context_chapter_window_after=1,
            api_v1_enabled=False,
        ),
        planner=MockDynamicPlanner(),
        text_provider=text_provider,
        workflow_run_repo=WorkflowRunRepository(db),
        workflow_step_repo=WorkflowStepRepository(db),
        agent_message_repo=AgentMessageRepository(db),
        agent_run_repo=AgentRunRepository(db),
        tool_call_repo=ToolCallRepository(db),
        skill_run_repo=SkillRunRepository(db),
        outline_service=outline_service,
        chapter_tool=ChapterGenerationTool(chapter_service),
        chapter_candidate_repo=ChapterCandidateRepository(db),
        consistency_service=consistency_service,
        revision_service=revision_service,
        project_repo=project_repo,
        outline_repo=outline_repo,
        user_repo=user_repo,
        schema_registry=schema_registry,
        skill_registry=skill_registry,
        skill_runtime=skill_runtime,
        agent_registry=agent_registry,
        evaluation_service=OnlineEvaluationService(
            repo=EvaluationRepository(db),
            schema_registry=schema_registry,
            schema_strict=True,
            schema_degrade_mode=False,
        ),
        retrieval_trace_repo=retrieval_trace_repo,
        retrieval_loop=retrieval_loop,
    )
