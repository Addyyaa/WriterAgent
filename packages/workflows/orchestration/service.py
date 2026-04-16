from __future__ import annotations

import copy
import hashlib
import json
import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


def _coerce_enforce_chapter_word_count(raw: Any) -> bool:
    """workflow_run.input_json 中的布尔偏好（缺省为 True）。"""
    if raw is None:
        return True
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(int(raw))
    s = str(raw).strip().lower()
    if s in ("0", "false", "no", "off"):
        return False
    if s in ("1", "true", "yes", "on"):
        return True
    return True


from packages.core.context_bundle_decision import mirror_context_bundle_lists_from_summary
from packages.core.tracing import new_request_id, new_trace_id, request_context
from packages.core.utils import ensure_non_empty_string
from packages.evaluation.writing import build_writing_score_breakdown
from packages.evaluation.service import OnlineEvaluationService
from packages.llm.embeddings.factory import create_embedding_provider_from_env
from packages.llm.text_generation.base import TextGenerationProvider, TextGenerationRequest
from packages.llm.text_generation.factory import create_text_generation_provider
from packages.memory.long_term.ingestion.ingestion_service import MemoryIngestionService
from packages.memory.long_term.runtime_config import MemoryRuntimeConfig
from packages.memory.long_term.search.search_service import MemorySearchService
from packages.memory.project_memory.project_memory_service import ProjectMemoryService
from packages.memory.working_memory.context_builder import ContextBuilder
from packages.memory.working_memory.hybrid_compressor import HybridContextCompressor
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
from packages.storage.postgres.repositories.story_state_snapshot_repository import (
    StoryStateSnapshotRepository,
)
from packages.storage.postgres.repositories.tool_call_repository import ToolCallRepository
from packages.storage.postgres.repositories.character_repository import CharacterRepository
from packages.storage.postgres.repositories.timeline_event_repository import TimelineEventRepository
from packages.storage.postgres.repositories.user_repository import UserRepository
from packages.storage.postgres.repositories.workflow_run_repository import (
    WorkflowRunRepository,
)
from packages.storage.postgres.repositories.workflow_step_repository import (
    WorkflowStepRepository,
)
from packages.storage.postgres.repositories.webhook_delivery_repository import (
    WebhookDeliveryRepository,
)
from packages.storage.postgres.repositories.webhook_subscription_repository import (
    WebhookSubscriptionRepository,
)
from packages.schemas import SchemaRegistry
from packages.skills import SkillRegistry, SkillRuntimeContext, SkillRuntimeEngine
from packages.skills.registry import SkillSpec
from packages.tools.chapter_tools.chapter_generation_tool import ChapterGenerationTool
from packages.tools.character_tools.inventory_tool import CharacterInventoryTool
from packages.webhooks.service import WebhookService
from packages.workflows.chapter_generation.context_provider import (
    SQLAlchemyStoryContextProvider,
)
from packages.workflows.orchestration.agent_output_envelope import build_agent_step_meta_raw
from packages.workflows.orchestration.agent_registry import AgentRegistry
from packages.workflows.chapter_generation.service import ChapterGenerationWorkflowService
from packages.workflows.chapter_generation.types import ChapterGenerationRequest
from packages.workflows.consistency_review.service import (
    ConsistencyReviewRequest,
    ConsistencyReviewWorkflowService,
)
from packages.workflows.orchestration.planner import DynamicPlanner, create_dynamic_planner
from packages.workflows.orchestration.planner_knowledge import (
    merge_planner_preferred_tools,
    merge_planner_retrieval_slots,
    merge_planner_verify_facts,
    planner_knowledge_meta,
)
from packages.workflows.orchestration.prompt_payload_assembler import (
    PromptPayloadAssembler,
    build_retrieval_bundle_from_raw_state,
    build_writer_alignment_supplement_text,
)
from packages.workflows.orchestration.retrieval_loop import (
    RetrievalLoopRequest,
    RetrievalLoopService,
    RetrievalLoopSummary,
)
from packages.workflows.orchestration.runtime_config import OrchestratorRuntimeConfig
from packages.workflows.orchestration.types import (
    PlannerPlan,
    WorkflowRunRequest,
    WorkflowRunResult,
)
from packages.workflows.outline_generation.service import (
    OutlineGenerationRequest,
    OutlineGenerationWorkflowService,
)
from packages.workflows.revision.service import RevisionRequest, RevisionWorkflowService


class WritingOrchestratorService:
    """异步写作编排器（DB 队列 + 动态 Planner + 多 Agent 步骤执行）。"""
    # 与 create_step 落库的 plan_* 对齐：均为可选，便于工具链/校验而不破坏历史 run
    AGENT_STEP_INPUT_SCHEMA = {
        "type": "object",
        "required": ["step_key", "workflow_type", "goal", "state", "role_id"],
        "properties": {
            "step_key": {"type": "string", "minLength": 1},
            "workflow_type": {"type": ["string", "null"]},
            "goal": {"type": ["string", "null"]},
            "state": {"type": "object"},
            "role_id": {"type": "string", "minLength": 1},
            "plan_required_slots": {
                "type": "array",
                "items": {"type": "string"},
                "description": "动态规划节点写入的检索槽位，供 planner_knowledge 合并",
            },
            "plan_preferred_tools": {"type": "array", "items": {"type": "string"}},
            "plan_must_verify_facts": {"type": "array", "items": {"type": "string"}},
            "plan_allowed_assumptions": {"type": "array", "items": {"type": "string"}},
            "plan_fallback_when_missing": {"type": ["string", "null"]},
            "focus_character_id": {
                "type": ["string", "null"],
                "description": "库存类槽位注入时的主角/焦点角色 ID（与 run.input_json 二选一）",
            },
        },
        "additionalProperties": True,
    }

    def __init__(
        self,
        *,
        runtime_config: OrchestratorRuntimeConfig,
        planner: DynamicPlanner,
        text_provider: TextGenerationProvider,
        workflow_run_repo: WorkflowRunRepository,
        workflow_step_repo: WorkflowStepRepository,
        agent_message_repo: AgentMessageRepository,
        agent_run_repo: AgentRunRepository,
        tool_call_repo: ToolCallRepository,
        skill_run_repo: SkillRunRepository,
        outline_service: OutlineGenerationWorkflowService,
        chapter_tool: ChapterGenerationTool,
        chapter_candidate_repo: ChapterCandidateRepository,
        consistency_service: ConsistencyReviewWorkflowService,
        revision_service: RevisionWorkflowService,
        project_repo: ProjectRepository,
        outline_repo: OutlineRepository | None = None,
        user_repo: UserRepository | None = None,
        schema_registry: SchemaRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        skill_runtime: SkillRuntimeEngine | None = None,
        agent_registry: AgentRegistry | None = None,
        evaluation_service: OnlineEvaluationService | None = None,
        retrieval_trace_repo: RetrievalTraceRepository | None = None,
        retrieval_loop: RetrievalLoopService | None = None,
        webhook_service: WebhookService | None = None,
        character_repo=None,
        timeline_repo=None,
        story_state_snapshot_repo: StoryStateSnapshotRepository | None = None,
    ) -> None:
        self.runtime_config = runtime_config
        self.planner = planner
        self.text_provider = text_provider
        self.workflow_run_repo = workflow_run_repo
        self.workflow_step_repo = workflow_step_repo
        self.agent_message_repo = agent_message_repo
        self.agent_run_repo = agent_run_repo
        self.tool_call_repo = tool_call_repo
        self.skill_run_repo = skill_run_repo
        self.outline_service = outline_service
        self.chapter_tool = chapter_tool
        self.chapter_candidate_repo = chapter_candidate_repo
        self.consistency_service = consistency_service
        self.revision_service = revision_service
        self.project_repo = project_repo
        self.outline_repo = outline_repo
        self.user_repo = user_repo
        self.schema_registry = schema_registry
        self.skill_registry = skill_registry
        self.skill_runtime = skill_runtime or SkillRuntimeEngine()
        self.agent_registry = agent_registry
        self.evaluation_service = evaluation_service
        self.retrieval_trace_repo = retrieval_trace_repo
        self.retrieval_loop = retrieval_loop
        self.webhook_service = webhook_service
        self._character_repo = character_repo
        self._timeline_repo = timeline_repo
        self.story_state_snapshot_repo = story_state_snapshot_repo
        self.prompt_payload_assembler = PromptPayloadAssembler()

    @classmethod
    def build_default(cls, db, text_provider: TextGenerationProvider | None = None) -> "WritingOrchestratorService":
        runtime_config = OrchestratorRuntimeConfig.from_env()
        memory_runtime = MemoryRuntimeConfig.from_env()
        chunk_size = max(64, int(memory_runtime.ingestion.chunk_size))
        chunk_overlap = max(0, min(int(memory_runtime.ingestion.chunk_overlap), chunk_size - 1))
        text_provider = text_provider or create_text_generation_provider()
        embedding_provider = create_embedding_provider_from_env()
        memory_repo = MemoryChunkRepository(db)
        memory_fact_repo = MemoryFactRepository(db)
        ingestion_service = MemoryIngestionService(
            chunker=SimpleTextChunker(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            ),
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
        project_memory_service = ProjectMemoryService(
            long_term_search=search_service,
            context_builder=ContextBuilder(
                compressor=HybridContextCompressor(
                    text_provider=text_provider,
                    enable_llm=memory_runtime.context_compression.enable_llm,
                    llm_trigger_ratio=memory_runtime.context_compression.llm_trigger_ratio,
                    llm_min_gain_ratio=memory_runtime.context_compression.llm_min_gain_ratio,
                    llm_max_input_chars=memory_runtime.context_compression.llm_max_input_chars,
                ),
                llm_max_items=memory_runtime.context_compression.llm_max_items,
                min_relevance_score=memory_runtime.context_compression.context_min_relevance_score,
                relative_score_floor=memory_runtime.context_compression.context_relative_score_floor,
                min_keep_rows=memory_runtime.context_compression.context_min_keep_rows,
                max_rows=memory_runtime.context_compression.context_max_rows,
            ),
        )
        project_repo = ProjectRepository(db)
        outline_repo = OutlineRepository(db)
        user_repo = UserRepository(db)
        chapter_repo = ChapterRepository(db)
        chapter_candidate_repo = ChapterCandidateRepository(db)
        context_provider = SQLAlchemyStoryContextProvider(db)

        root = Path.cwd()
        schema_root = Path(runtime_config.schema_root)
        if not schema_root.is_absolute():
            schema_root = (root / schema_root).resolve()
        skill_root = Path(runtime_config.skill_config_root)
        if not skill_root.is_absolute():
            skill_root = (root / skill_root).resolve()
        agent_root = Path(runtime_config.agent_config_root)
        if not agent_root.is_absolute():
            agent_root = (root / agent_root).resolve()

        schema_registry = SchemaRegistry(schema_root)
        skill_registry = SkillRegistry(
            root=skill_root,
            schema_registry=schema_registry,
            strict=runtime_config.schema_strict,
            degrade_mode=runtime_config.schema_degrade_mode,
        )
        agent_registry = AgentRegistry(
            root=agent_root,
            schema_registry=schema_registry,
            skill_registry=skill_registry,
            strict=runtime_config.schema_strict,
            degrade_mode=runtime_config.schema_degrade_mode,
            consumption_strict=runtime_config.schema_consumption_strict,
            consumption_degrade_mode=runtime_config.schema_consumption_degrade_mode,
        )
        skill_runtime = SkillRuntimeEngine(
            fail_open=runtime_config.skill_runtime_fail_open,
            strict_fail_close=runtime_config.skill_runtime_strict_fail_close,
            default_execution_mode=runtime_config.skill_runtime_default_execution_mode,
            default_fallback_policy=runtime_config.skill_runtime_default_fallback_policy,
            require_effect_trace=runtime_config.skill_runtime_require_effect_trace,
        )

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
            default_context_token_budget=memory_runtime.context_compression.context_token_budget_default,
            agent_registry=agent_registry,
            schema_registry=schema_registry,
            skill_runtime=skill_runtime,
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
            agent_registry=agent_registry,
            schema_registry=schema_registry,
            skill_runtime=skill_runtime,
        )

        evaluation_service = None
        if runtime_config.eval_online_enabled:
            evaluation_service = OnlineEvaluationService(
                repo=EvaluationRepository(db),
                schema_registry=schema_registry,
                schema_strict=runtime_config.schema_strict,
                schema_degrade_mode=runtime_config.schema_degrade_mode,
            )

        retrieval_trace_repo = RetrievalTraceRepository(db)
        webhook_service = WebhookService(
            subscription_repo=WebhookSubscriptionRepository(db),
            delivery_repo=WebhookDeliveryRepository(db),
        )
        story_snap_repo = StoryStateSnapshotRepository(db)
        retrieval_loop = RetrievalLoopService(
            runtime_config=runtime_config,
            project_memory_service=project_memory_service,
            story_context_provider=context_provider,
            project_repo=project_repo,
            outline_repo=outline_repo,
            user_repo=user_repo,
            retrieval_trace_repo=retrieval_trace_repo,
            inventory_tool=CharacterInventoryTool(db),
            story_state_snapshot_repo=story_snap_repo,
        )

        return cls(
            runtime_config=runtime_config,
            planner=create_dynamic_planner(),
            text_provider=text_provider,
            workflow_run_repo=WorkflowRunRepository(db),
            workflow_step_repo=WorkflowStepRepository(db),
            agent_message_repo=AgentMessageRepository(db),
            agent_run_repo=AgentRunRepository(db),
            tool_call_repo=ToolCallRepository(db),
            skill_run_repo=SkillRunRepository(db),
            outline_service=outline_service,
            chapter_tool=ChapterGenerationTool(chapter_service),
            chapter_candidate_repo=chapter_candidate_repo,
            consistency_service=consistency_service,
            revision_service=revision_service,
            project_repo=project_repo,
            outline_repo=outline_repo,
            user_repo=user_repo,
            schema_registry=schema_registry,
            skill_registry=skill_registry,
            skill_runtime=skill_runtime,
            agent_registry=agent_registry,
            evaluation_service=evaluation_service,
            retrieval_trace_repo=retrieval_trace_repo,
            retrieval_loop=retrieval_loop,
            webhook_service=webhook_service,
            character_repo=CharacterRepository(db),
            timeline_repo=TimelineEventRepository(db),
            story_state_snapshot_repo=story_snap_repo,
        )

    def create_run(self, request: WorkflowRunRequest) -> WorkflowRunResult:
        request_id = request.request_id or new_request_id()
        trace_id = request.trace_id or new_trace_id()
        writing_goal = ensure_non_empty_string(request.writing_goal, field_name="writing_goal")
        initiated_by = self._resolve_initiated_by(request.user_id)

        row = self.workflow_run_repo.create_run(
            project_id=request.project_id,
            workflow_type=request.workflow_type,
            trace_id=trace_id,
            request_id=request_id,
            initiated_by=initiated_by,
            idempotency_key=request.idempotency_key,
            input_json={
                "writing_goal": writing_goal,
                "chapter_no": request.chapter_no,
                "target_words": request.target_words,
                "style_hint": request.style_hint,
                "include_memory_top_k": request.include_memory_top_k,
                "context_token_budget": request.context_token_budget,
                "temperature": request.temperature,
                "chat_turns": list(request.chat_turns or []),
                "working_notes": list(request.working_notes or []),
                "session_id": request.session_id,
                "metadata_json": request.metadata_json,
                "enforce_chapter_word_count": bool(request.enforce_chapter_word_count),
            },
            max_retries=self.runtime_config.default_max_retries,
        )
        if self.webhook_service is not None:
            try:
                self.webhook_service.enqueue_event(
                    project_id=request.project_id,
                    event_type="writing.run.created",
                    payload_json={
                        "run_id": str(row.id),
                        "workflow_type": request.workflow_type,
                        "trace_id": trace_id,
                    },
                    trace_id=trace_id,
                    request_id=request_id,
                )
            except Exception:
                pass
        return WorkflowRunResult(
            run_id=str(row.id),
            status=str(row.status),
            trace_id=trace_id,
            request_id=request_id,
        )

    def _resolve_initiated_by(self, user_id: str | None):
        if user_id is None:
            return None
        raw = str(user_id).strip()
        if not raw:
            return None
        try:
            user_uuid = UUID(raw)
        except ValueError as exc:
            raise ValueError("user_id 必须是合法 UUID") from exc

        if self.user_repo is None:
            return user_uuid
        user = self.user_repo.get(user_uuid)
        if user is None:
            raise ValueError("user_id 不存在")
        return user_uuid

    def get_run_detail(self, run_id) -> dict[str, Any] | None:
        row = self.workflow_run_repo.get(run_id)
        if row is None:
            return None
        steps = self.workflow_step_repo.list_by_run(workflow_run_id=row.id)
        messages = self.agent_message_repo.list_by_run(workflow_run_id=row.id, limit=200)
        candidates = self.chapter_candidate_repo.list_by_run(workflow_run_id=row.id)
        retrieval_round_rows = []
        retrieval_evidence_rows = []
        if self.retrieval_trace_repo is not None:
            try:
                retrieval_round_rows = self.retrieval_trace_repo.list_rounds_by_run(workflow_run_id=row.id)
                retrieval_evidence_rows = self.retrieval_trace_repo.list_evidence_by_run(workflow_run_id=row.id)
            except Exception:
                retrieval_round_rows = []
                retrieval_evidence_rows = []
        evidence_by_round: dict[int, list[dict[str, Any]]] = {}
        for item in retrieval_evidence_rows:
            key = int(item.retrieval_round_id)
            evidence_by_round.setdefault(key, []).append(
                {
                    "id": int(item.id),
                    "source_type": item.source_type,
                    "source_id": item.source_id,
                    "chunk_id": item.chunk_id,
                    "score": float(item.score) if item.score is not None else None,
                    "adopted": bool(item.adopted),
                    "text": item.evidence_text,
                    "metadata_json": dict(item.metadata_json or {}),
                }
            )
        retrieval_rounds = [
            {
                "id": int(round_row.id),
                "retrieval_trace_id": round_row.retrieval_trace_id,
                "step_key": round_row.step_key,
                "workflow_type": round_row.workflow_type,
                "round_index": int(round_row.round_index),
                "query": round_row.query,
                "intent": round_row.intent,
                "source_types": list(round_row.source_types_json or []),
                "time_scope": dict(round_row.time_scope_json or {}),
                "chapter_window": dict(round_row.chapter_window_json or {}),
                "must_have_slots": list(round_row.must_have_slots_json or []),
                "enough_context": bool(round_row.enough_context),
                "coverage_score": float(round_row.coverage_score or 0.0),
                "new_evidence_gain": float(round_row.new_evidence_gain or 0.0),
                "stop_reason": round_row.stop_reason,
                "latency_ms": int(round_row.latency_ms) if round_row.latency_ms is not None else None,
                "decision_json": dict(round_row.decision_json or {}),
                "evidence_items": evidence_by_round.get(int(round_row.id), []),
            }
            for round_row in retrieval_round_rows
        ]
        if not retrieval_rounds:
            for step in steps:
                output_json = dict(step.output_json or {})
                step_rounds = list(output_json.get("retrieval_rounds") or [])
                trace_id = output_json.get("retrieval_trace_id")
                for item in step_rounds:
                    retrieval_rounds.append(
                        {
                            "id": None,
                            "retrieval_trace_id": trace_id,
                            "step_key": str(step.step_key),
                            "workflow_type": str((step.input_json or {}).get("workflow_type") or step.step_type),
                            "round_index": int(item.get("round_index") or 0),
                            "query": item.get("query"),
                            "intent": item.get("intent"),
                            "source_types": list(item.get("source_types") or []),
                            "time_scope": {},
                            "chapter_window": {},
                            "must_have_slots": list(item.get("must_have_slots") or []),
                            "enough_context": False,
                            "coverage_score": float(item.get("coverage_score") or 0.0),
                            "new_evidence_gain": float(item.get("new_evidence_gain") or 0.0),
                            "stop_reason": item.get("stop_reason"),
                            "latency_ms": item.get("latency_ms"),
                            "decision_json": {
                                "resolved_slots": list(item.get("resolved_slots") or []),
                                "open_slots": list(item.get("open_slots") or []),
                            },
                            "evidence_items": [],
                        }
                    )
        latest_round = retrieval_rounds[-1] if retrieval_rounds else None
        open_slots = []
        if latest_round is not None:
            open_slots = list((latest_round.get("decision_json") or {}).get("open_slots") or [])
        mock_mode = any(bool((step.output_json or {}).get("mock_mode")) for step in steps)
        return {
            "id": str(row.id),
            "project_id": str(row.project_id),
            "workflow_type": row.workflow_type,
            "status": str(row.status),
            "trace_id": row.trace_id,
            "request_id": row.request_id,
            "retry_count": int(row.retry_count or 0),
            "max_retries": int(row.max_retries or 0),
            "input_json": dict(row.input_json or {}),
            "plan_json": dict(row.plan_json or {}),
            "output_json": dict(row.output_json or {}),
            "error_code": row.error_code,
            "error_message": row.error_message,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            "claimed_by": row.claimed_by,
            "claimed_at": row.claimed_at.isoformat() if row.claimed_at else None,
            "heartbeat_at": row.heartbeat_at.isoformat() if row.heartbeat_at else None,
            "lease_expires_at": row.lease_expires_at.isoformat() if row.lease_expires_at else None,
            "role_trace": [str(step.role_id) for step in steps if step.role_id],
            "strategy_versions": {
                str(step.step_key): str(step.strategy_version)
                for step in steps
                if step.strategy_version
            },
            "retrieval_rounds": retrieval_rounds,
            "retrieval_stop_reason": latest_round.get("stop_reason") if latest_round is not None else None,
            "evidence_coverage": latest_round.get("coverage_score") if latest_round is not None else None,
            "open_slots": open_slots,
            "mock_mode": mock_mode,
            "steps": [
                {
                    "id": int(step.id),
                    "step_key": step.step_key,
                    "step_type": step.step_type,
                    "workflow_type": str((step.input_json or {}).get("workflow_type") or step.step_type),
                    "role_id": step.role_id,
                    "strategy_version": step.strategy_version,
                    "prompt_hash": step.prompt_hash,
                    "schema_version": step.schema_version,
                    "status": str(step.status),
                    "attempt_count": int(step.attempt_count or 0),
                    "depends_on": list(step.depends_on_keys or []),
                    "input_json": dict(step.input_json or {}),
                    "output_json": dict(step.output_json or {}),
                    "checkpoint_json": dict(step.checkpoint_json or {}),
                    "heartbeat_at": step.heartbeat_at.isoformat() if step.heartbeat_at else None,
                    "last_progress_at": step.last_progress_at.isoformat() if step.last_progress_at else None,
                    "error_code": step.error_code,
                    "error_message": step.error_message,
                    "started_at": step.started_at.isoformat() if step.started_at else None,
                    "finished_at": step.finished_at.isoformat() if step.finished_at else None,
                }
                for step in steps
            ],
            "candidates": [
                {
                    "id": str(item.id),
                    "workflow_step_id": int(item.workflow_step_id) if item.workflow_step_id is not None else None,
                    "chapter_no": int(item.chapter_no),
                    "title": item.title,
                    "status": str(item.status),
                    "trace_id": item.trace_id,
                    "request_id": item.request_id,
                    "approved_chapter_id": str(item.approved_chapter_id) if item.approved_chapter_id is not None else None,
                    "approved_version_id": int(item.approved_version_id) if item.approved_version_id is not None else None,
                    "memory_chunks_count": int(item.memory_chunks_count or 0),
                    "expires_at": item.expires_at.isoformat() if item.expires_at else None,
                    "approved_at": item.approved_at.isoformat() if item.approved_at else None,
                    "rejected_at": item.rejected_at.isoformat() if item.rejected_at else None,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                }
                for item in candidates
            ],
            "messages": [
                {
                    "id": int(msg.id),
                    "workflow_step_id": int(msg.workflow_step_id) if msg.workflow_step_id is not None else None,
                    "role": str(msg.role),
                    "sender": msg.sender,
                    "receiver": msg.receiver,
                    "content": msg.content,
                    "metadata_json": dict(msg.metadata_json or {}),
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                }
                for msg in messages
            ],
        }

    def cancel_run(self, run_id) -> bool:
        row = self.workflow_run_repo.cancel(run_id)
        if row is None:
            return False
        self.workflow_step_repo.cancel_pending_steps(workflow_run_id=row.id)
        if self.webhook_service is not None:
            try:
                self.webhook_service.enqueue_event(
                    project_id=row.project_id,
                    event_type="writing.run.cancelled",
                    payload_json={"run_id": str(row.id), "trace_id": row.trace_id},
                    trace_id=row.trace_id,
                    request_id=row.request_id,
                )
            except Exception:
                pass
        return True

    def retry_run(self, run_id) -> bool:
        row = self.workflow_run_repo.retry_run(run_id)
        if row is None:
            return False
        self.workflow_step_repo.reset_for_retry(workflow_run_id=row.id)
        if self.webhook_service is not None:
            try:
                self.webhook_service.enqueue_event(
                    project_id=row.project_id,
                    event_type="writing.run.running",
                    payload_json={"run_id": str(row.id), "trace_id": row.trace_id, "reason": "manual_retry"},
                    trace_id=row.trace_id,
                    request_id=row.request_id,
                )
            except Exception:
                pass
        return True

    def approve_candidate(self, candidate_id, *, approved_by) -> dict[str, Any] | None:
        candidate = self.chapter_candidate_repo.get(candidate_id)
        if candidate is None:
            return None
        if str(candidate.status) == "approved":
            return {
                "candidate_id": str(candidate.id),
                "status": "approved",
                "chapter_id": str(candidate.approved_chapter_id) if candidate.approved_chapter_id else None,
                "version_id": int(candidate.approved_version_id) if candidate.approved_version_id else None,
                "memory_chunks": int(candidate.memory_chunks_count or 0),
                "run_id": str(candidate.workflow_run_id) if candidate.workflow_run_id else None,
            }
        if str(candidate.status) != "pending":
            raise RuntimeError(f"candidate 状态不可审批: {candidate.status}")

        now = datetime.now(tz=timezone.utc)
        if candidate.expires_at is not None and candidate.expires_at <= now:
            candidate.status = "expired"
            self.chapter_candidate_repo.db.commit()
            raise RuntimeError("candidate 已过期")

        chapter_repo = self.chapter_tool.workflow_service.chapter_repo
        chapter_row, version_row, _ = chapter_repo.save_generated_draft(
            project_id=candidate.project_id,
            chapter_no=int(candidate.chapter_no),
            title=candidate.title,
            content=candidate.content,
            summary=candidate.summary,
            source_agent="writer_agent",
            source_workflow="chapter_generation",
            trace_id=candidate.trace_id,
        )

        ingestion_rows = self.chapter_tool.workflow_service.ingestion_service.ingest_text(
            project_id=candidate.project_id,
            text=str(candidate.content or ""),
            source_type="chapter",
            source_id=chapter_row.id,
            chunk_type="chapter_body",
            metadata_json={
                "chapter_no": int(chapter_row.chapter_no),
                "trace_id": candidate.trace_id,
                "approved_candidate_id": str(candidate.id),
            },
            source_timestamp=datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            replace_existing=True,
        )

        approved = self.chapter_candidate_repo.approve(
            candidate.id,
            approved_by=approved_by,
            approved_chapter_id=chapter_row.id,
            approved_version_id=version_row.id,
            memory_chunks_count=len(ingestion_rows),
        )

        if approved is None:
            raise RuntimeError("candidate 审批失败")

        if self.story_state_snapshot_repo is not None:
            try:
                self.story_state_snapshot_repo.upsert_for_chapter(
                    project_id=candidate.project_id,
                    chapter_no=int(chapter_row.chapter_no),
                    state_json={
                        "chapter_no": int(chapter_row.chapter_no),
                        "title": chapter_row.title,
                        "summary_excerpt": (chapter_row.summary or "")[:4000],
                        "approved_via": "chapter_candidate",
                        "candidate_id": str(candidate.id),
                        "location": None,
                        "party": [],
                        "relationships": [],
                        "knowledge": [],
                        "identity_exposure": [],
                    },
                    source="candidate_approve",
                )
            except Exception:
                logger.warning("写入故事状态快照失败 project=%s ch=%s", candidate.project_id, chapter_row.chapter_no, exc_info=True)

        if approved.workflow_run_id is not None and approved.workflow_step_id is not None:
            step_row = self.workflow_step_repo.get(approved.workflow_step_id)
            if step_row is not None:
                output = dict(step_row.output_json or {})
                output["chapter"] = {
                    "id": str(chapter_row.id),
                    "chapter_no": int(chapter_row.chapter_no),
                    "title": chapter_row.title,
                    "summary": chapter_row.summary,
                    "content": chapter_row.content,
                    "draft_version": int(chapter_row.draft_version),
                    "version_id": int(version_row.id),
                }
                output["memory_ingestion"] = {
                    "created_chunks": len(ingestion_rows),
                    "persisted": True,
                }
                output["waiting_review"] = False
                if "candidate" in output:
                    output["candidate"]["status"] = "approved"
                    output["candidate"]["id"] = str(approved.id)
                self.workflow_step_repo.update_output_json(
                    workflow_run_id=approved.workflow_run_id,
                    step_key=str(step_row.step_key),
                    output_json=output,
                )
            self.workflow_run_repo.resume_from_waiting_review(approved.workflow_run_id)

        if self.webhook_service is not None:
            try:
                self.webhook_service.enqueue_event(
                    project_id=approved.project_id,
                    event_type="chapter.candidate.approved",
                    payload_json={
                        "candidate_id": str(approved.id),
                        "run_id": str(approved.workflow_run_id) if approved.workflow_run_id else None,
                        "chapter_id": str(chapter_row.id),
                        "version_id": int(version_row.id),
                    },
                    trace_id=approved.trace_id,
                    request_id=approved.request_id,
                )
                if approved.workflow_run_id is not None:
                    self.webhook_service.enqueue_event(
                        project_id=approved.project_id,
                        event_type="writing.run.running",
                        payload_json={
                            "run_id": str(approved.workflow_run_id),
                            "trace_id": approved.trace_id,
                            "reason": "candidate_approved",
                        },
                        trace_id=approved.trace_id,
                        request_id=approved.request_id,
                    )
            except Exception:
                pass

        return {
            "candidate_id": str(approved.id),
            "status": "approved",
            "chapter_id": str(chapter_row.id),
            "version_id": int(version_row.id),
            "memory_chunks": len(ingestion_rows),
            "run_id": str(approved.workflow_run_id) if approved.workflow_run_id else None,
        }

    def reject_candidate(self, candidate_id, *, rejected_by, cancel_run: bool = True) -> dict[str, Any] | None:
        candidate = self.chapter_candidate_repo.get(candidate_id)
        if candidate is None:
            return None
        if str(candidate.status) == "rejected":
            return {
                "candidate_id": str(candidate.id),
                "status": "rejected",
                "run_id": str(candidate.workflow_run_id) if candidate.workflow_run_id else None,
            }
        if str(candidate.status) != "pending":
            raise RuntimeError(f"candidate 状态不可拒绝: {candidate.status}")

        row = self.chapter_candidate_repo.reject(candidate.id, rejected_by=rejected_by)
        if row is None:
            raise RuntimeError("candidate 拒绝失败")

        run_status = None
        if row.workflow_run_id is not None:
            if cancel_run:
                self.workflow_run_repo.cancel(row.workflow_run_id)
                self.workflow_step_repo.cancel_pending_steps(workflow_run_id=row.workflow_run_id)
                run_status = "cancelled"
            else:
                self.workflow_run_repo.mark_waiting_review(row.workflow_run_id)
                run_status = "waiting_review"

        if self.webhook_service is not None:
            try:
                self.webhook_service.enqueue_event(
                    project_id=row.project_id,
                    event_type="chapter.candidate.rejected",
                    payload_json={
                        "candidate_id": str(row.id),
                        "run_id": str(row.workflow_run_id) if row.workflow_run_id else None,
                        "run_status": run_status,
                    },
                    trace_id=row.trace_id,
                    request_id=row.request_id,
                )
            except Exception:
                pass

        return {
            "candidate_id": str(row.id),
            "status": "rejected",
            "run_id": str(row.workflow_run_id) if row.workflow_run_id else None,
            "run_status": run_status,
        }

    def _recover_stale_runs(self) -> list[Any]:
        recovered = self.workflow_run_repo.recover_stale_running(
            heartbeat_stale_seconds=self.runtime_config.recover_heartbeat_stale_seconds,
            legacy_run_started_stale_seconds=self.runtime_config.max_step_seconds,
        )
        if recovered:
            logger.info("recovered %d stale runs (lease/heartbeat)", len(recovered))
        for row in recovered:
            if str(row.status) == "queued":
                self.workflow_step_repo.reset_for_retry(workflow_run_id=row.id)
        return recovered

    def startup_recover_stale_runs(self) -> int:
        """进程启动时回收僵尸 running（worker / API 入口可调用）。"""
        return len(self._recover_stale_runs())

    def process_once(self, *, limit: int | None = None) -> int:
        self._recover_stale_runs()

        claimed = self.workflow_run_repo.claim_next(
            limit=limit or self.runtime_config.worker_batch_size,
            worker_id=self.runtime_config.worker_instance_id,
            initial_lease_seconds=self.runtime_config.run_initial_lease_seconds,
        )
        processed = 0
        for row in claimed:
            processed += 1
            logger.info("claimed run %s (workflow=%s)", row.id, row.workflow_type)
            self._execute_run(row.id)
        return processed

    def _execute_run(self, run_id) -> None:
        row = self.workflow_run_repo.get(run_id)
        if row is None:
            logger.warning("run %s not found, skipping", run_id)
            return

        logger.info("execute_run start run=%s project=%s workflow=%s", row.id, row.project_id, row.workflow_type)
        started_at = perf_counter()
        evaluation_run = None
        with request_context(request_id=row.request_id or new_request_id(), trace_id=row.trace_id or new_trace_id()):
            try:
                if self.webhook_service is not None:
                    try:
                        self.webhook_service.enqueue_event(
                            project_id=row.project_id,
                            event_type="writing.run.running",
                            payload_json={
                                "run_id": str(row.id),
                                "workflow_type": row.workflow_type,
                                "trace_id": row.trace_id,
                            },
                            trace_id=row.trace_id,
                            request_id=row.request_id,
                        )
                    except Exception:
                        pass
                if self.evaluation_service is not None:
                    evaluation_run = self.evaluation_service.start_writing_run(
                        project_id=row.project_id,
                        workflow_run_id=row.id,
                        request_id=row.request_id,
                        context_json={
                            "workflow_type": row.workflow_type,
                            "trace_id": row.trace_id,
                        },
                    )
                self._ensure_plan_and_steps(row.id)
                self._execute_steps_loop(
                    row.id,
                    evaluation_run_id=evaluation_run.id if evaluation_run is not None else None,
                    run_started_at=started_at,
                )
                latest = self.workflow_run_repo.get(row.id)
                if latest is not None and str(latest.status) == "waiting_review":
                    return
                detail = self.get_run_detail(row.id) or {}
                latency_ms = int((perf_counter() - started_at) * 1000)
                score_breakdown = build_writing_score_breakdown(detail)
                if self.evaluation_service is not None and evaluation_run is not None:
                    self.evaluation_service.complete_writing_run(
                        evaluation_run_id=evaluation_run.id,
                        project_id=row.project_id,
                        workflow_run_id=row.id,
                        score_breakdown=score_breakdown,
                        context_json={"latency_ms": latency_ms},
                    )
                logger.info("run %s completed latency=%dms", row.id, latency_ms)
                self.workflow_run_repo.succeed(
                    row.id,
                    output_json={
                        "latency_ms": latency_ms,
                        "evaluation_run_id": str(evaluation_run.id) if evaluation_run is not None else None,
                        "evaluation_score_breakdown": score_breakdown,
                        "final": detail.get("steps", []),
                    },
                )
                if self.webhook_service is not None:
                    try:
                        self.webhook_service.enqueue_event(
                            project_id=row.project_id,
                            event_type="writing.run.success",
                            payload_json={
                                "run_id": str(row.id),
                                "trace_id": row.trace_id,
                            },
                            trace_id=row.trace_id,
                            request_id=row.request_id,
                        )
                    except Exception:
                        pass
            except Exception as exc:
                logger.error("run %s failed: %s: %s", row.id, type(exc).__name__, exc, exc_info=True)
                retryable = isinstance(exc, RuntimeError)
                if self.evaluation_service is not None and evaluation_run is not None:
                    try:
                        self.evaluation_service.fail_writing_run(
                            evaluation_run_id=evaluation_run.id,
                            error_message=str(exc),
                            context_json={"error_code": type(exc).__name__},
                        )
                    except Exception:
                        pass
                self.workflow_run_repo.fail(
                    row.id,
                    error_code=type(exc).__name__,
                    error_message=str(exc),
                    retryable=retryable,
                    retry_delay_seconds=self.runtime_config.default_retry_delay_seconds,
                )
                if self.webhook_service is not None:
                    try:
                        self.webhook_service.enqueue_event(
                            project_id=row.project_id,
                            event_type="writing.run.failed",
                            payload_json={
                                "run_id": str(row.id),
                                "trace_id": row.trace_id,
                                "error": str(exc),
                            },
                            trace_id=row.trace_id,
                            request_id=row.request_id,
                        )
                    except Exception:
                        pass

    def _ensure_plan_and_steps(self, run_id) -> None:
        row = self.workflow_run_repo.get(run_id)
        if row is None:
            raise RuntimeError("workflow run 不存在")

        existing_steps = self.workflow_step_repo.list_by_run(workflow_run_id=row.id)
        if existing_steps:
            return

        project = self.project_repo.get(row.project_id)
        context_json = {
            "project": {
                "title": project.title if project is not None else None,
                "genre": project.genre if project is not None else None,
                "premise": project.premise if project is not None else None,
                **(
                    {
                        "target_audience": (getattr(project, "metadata_json", None) or {}).get("target_audience"),
                        "tone": (getattr(project, "metadata_json", None) or {}).get("tone"),
                        "tags": (getattr(project, "metadata_json", None) or {}).get("tags"),
                    }
                    if project is not None
                    else {}
                ),
            },
            "input": dict(row.input_json or {}),
        }

        req = WorkflowRunRequest(
            project_id=row.project_id,
            writing_goal=str((row.input_json or {}).get("writing_goal") or ""),
            workflow_type=row.workflow_type,
            chapter_no=(row.input_json or {}).get("chapter_no"),
            target_words=int((row.input_json or {}).get("target_words") or 1200),
            style_hint=(row.input_json or {}).get("style_hint"),
            include_memory_top_k=int((row.input_json or {}).get("include_memory_top_k") or 8),
            context_token_budget=(
                int((row.input_json or {}).get("context_token_budget"))
                if (row.input_json or {}).get("context_token_budget") is not None
                else None
            ),
            temperature=float((row.input_json or {}).get("temperature") or 0.7),
            chat_turns=list((row.input_json or {}).get("chat_turns") or []),
            working_notes=list((row.input_json or {}).get("working_notes") or []),
            session_id=(row.input_json or {}).get("session_id"),
            user_id=str(row.initiated_by) if row.initiated_by is not None else None,
            request_id=row.request_id,
            trace_id=row.trace_id,
            idempotency_key=row.idempotency_key,
            enforce_chapter_word_count=_coerce_enforce_chapter_word_count(
                (row.input_json or {}).get("enforce_chapter_word_count"),
            ),
        )

        plan = self.planner.plan(req, context_json=context_json)
        self.workflow_run_repo.set_plan(run_id, plan_json=self._plan_to_json(plan))

        for node in plan.nodes:
            role_id = str(node.role_id or node.agent_name or "").strip() or None
            strategy_version = None
            prompt_hash = None
            schema_version = None

            if self.agent_registry is not None and role_id:
                profile, strategy, _, _ = self.agent_registry.resolve(
                    role_id=role_id,
                    workflow_type=node.workflow_type,
                    step_key=node.step_key,
                    strategy_mode=node.strategy_mode,
                )
                strategy_version = strategy.version
                schema_version = profile.schema_version
                prompt_hash = hashlib.sha256(profile.prompt.encode("utf-8")).hexdigest()[:16]

            base_inp = dict(node.input_json or {})
            plan_inp: dict[str, Any] = {}
            if getattr(node, "required_slots", None):
                plan_inp["plan_required_slots"] = list(node.required_slots)
            if getattr(node, "preferred_tools", None):
                plan_inp["plan_preferred_tools"] = list(node.preferred_tools)
            if getattr(node, "must_verify_facts", None):
                plan_inp["plan_must_verify_facts"] = list(node.must_verify_facts)
            if getattr(node, "allowed_assumptions", None):
                plan_inp["plan_allowed_assumptions"] = list(node.allowed_assumptions)
            if getattr(node, "fallback_when_missing", None) and str(node.fallback_when_missing or "").strip():
                plan_inp["plan_fallback_when_missing"] = str(node.fallback_when_missing).strip()
            self.workflow_step_repo.create_step(
                workflow_run_id=row.id,
                step_key=node.step_key,
                step_type=node.step_type,
                agent_name=node.agent_name,
                role_id=role_id,
                strategy_version=strategy_version,
                prompt_hash=prompt_hash,
                schema_version=schema_version,
                depends_on_keys=node.depends_on,
                input_json={
                    **base_inp,
                    **plan_inp,
                    "workflow_type": node.workflow_type,
                    "strategy_mode": node.strategy_mode,
                },
                status="pending",
            )

    def _execute_steps_loop(self, run_id, *, evaluation_run_id=None, run_started_at: float | None = None) -> None:
        row = self.workflow_run_repo.get(run_id)
        if row is None:
            raise RuntimeError("workflow run 不存在")

        while True:
            if run_started_at is not None:
                elapsed = perf_counter() - run_started_at
                if elapsed > float(self.runtime_config.workflow_run_timeout_seconds):
                    raise TimeoutError(
                        f"workflow run 超时（>{self.runtime_config.workflow_run_timeout_seconds}s）"
                    )
            current = self.workflow_run_repo.get(run_id)
            if current is None:
                raise RuntimeError("workflow run 丢失")
            if str(current.status) == "cancelled":
                self.workflow_step_repo.cancel_pending_steps(workflow_run_id=run_id)
                return
            if str(current.status) == "waiting_review":
                return

            steps = self.workflow_step_repo.list_by_run(workflow_run_id=run_id)
            failed = [item for item in steps if str(item.status) == "failed"]
            if failed:
                raise RuntimeError(f"步骤失败: {failed[0].step_key}")

            pending = [item for item in steps if str(item.status) in {"pending", "queued"}]
            running = [item for item in steps if str(item.status) == "running"]
            if not pending and not running:
                return

            ready = self.workflow_step_repo.list_ready_steps(workflow_run_id=run_id)
            if not ready:
                blocked = [item.step_key for item in pending]
                raise RuntimeError(f"不存在可执行步骤，可能存在依赖环: {blocked}")

            for step in ready:
                self._execute_single_step(run_id, step.id, evaluation_run_id=evaluation_run_id)

    def _execute_single_step(self, run_id, step_id, *, evaluation_run_id=None) -> None:
        row = self.workflow_run_repo.get(run_id)
        step = self.workflow_step_repo.get(step_id)
        if row is None or step is None:
            raise RuntimeError("步骤执行上下文不存在")

        logger.info("step start run=%s step=%s key=%s type=%s", run_id, step.id, step.step_key, step.step_type)
        step_started_at = perf_counter()
        self.workflow_step_repo.start(step.id)
        self.workflow_run_repo.touch_execution_lease(
            run_id,
            worker_id=self.runtime_config.worker_instance_id,
            extend_seconds=self.runtime_config.run_lease_extend_seconds,
        )
        workflow_type = str((step.input_json or {}).get("workflow_type") or step.step_type)
        role_id = str(step.role_id or step.agent_name or "unknown_agent")
        strategy_version = step.strategy_version
        prompt_hash = step.prompt_hash
        schema_version = step.schema_version
        resolved_skills: list[SkillSpec] = []
        skill_warnings: list[str] = []

        if self.agent_registry is not None:
            profile, strategy, skills, warnings = self.agent_registry.resolve(
                role_id=role_id,
                workflow_type=workflow_type,
                step_key=str(step.step_key),
                strategy_mode=(step.input_json or {}).get("strategy_mode"),
            )
            strategy_version = strategy.version
            prompt_hash = hashlib.sha256(profile.prompt.encode("utf-8")).hexdigest()[:16]
            schema_version = profile.schema_version
            skill_warnings = [str(item) for item in list(warnings or []) if str(item).strip()]
            skill_warnings.extend(
                [str(item) for item in list(profile.consumption_warnings or []) if str(item).strip()]
            )
            resolved_skills = list(skills or [])
        if not resolved_skills:
            resolved_skills = [
                SkillSpec(
                    id=(f"{step.agent_name}.execute" if step.agent_name else "step.execute"),
                    name=(f"{step.agent_name}.execute" if step.agent_name else "step.execute"),
                    version="v1",
                    description="fallback step skill",
                    tags=["fallback"],
                )
            ]

        agent_run = self.agent_run_repo.create_run(
            trace_id=row.trace_id or new_trace_id(),
            request_id=row.request_id,
            project_id=row.project_id,
            agent_name=step.agent_name or "unknown_agent",
            task_type=workflow_type,
            role_id=role_id,
            strategy_version=strategy_version,
            prompt_hash=prompt_hash,
            schema_version=schema_version,
            input_json=dict(step.input_json or {}),
        )
        self.agent_run_repo.start(agent_run.id)

        call = self.tool_call_repo.create_call(
            trace_id=row.trace_id or new_trace_id(),
            agent_run_id=agent_run.id,
            tool_name="orchestrator_step_dispatch",
            role_id=role_id,
            strategy_version=strategy_version,
            prompt_hash=prompt_hash,
            schema_version=schema_version,
            input_json={"step_key": step.step_key, "step_type": step.step_type},
        )
        self.tool_call_repo.start(call.id)

        skill_run_rows: list[tuple[SkillSpec, Any]] = []
        for spec in resolved_skills:
            skill_row = self.skill_run_repo.create_run(
                trace_id=row.trace_id or new_trace_id(),
                agent_run_id=agent_run.id,
                skill_name=spec.id,
                skill_version=spec.version,
                role_id=role_id,
                strategy_version=strategy_version,
                prompt_hash=prompt_hash,
                schema_version=schema_version,
                input_snapshot_json={
                    **dict(step.input_json or {}),
                    "skill_warnings": list(skill_warnings),
                },
            )
            self.skill_run_repo.start(skill_row.id)
            skill_run_rows.append((spec, skill_row.id))

        try:
            raw_state = self._build_state(run_id)
            output = self._dispatch_step(
                row=row,
                step=step,
                raw_state=raw_state,
                resolved_skills=resolved_skills,
                skill_warnings=skill_warnings,
            )
            self.workflow_step_repo.succeed(step.id, output_json=output)
            skill_snapshots_by_id = {
                str(item.get("skill_id")): dict(item)
                for item in list(output.get("skill_runs") or [])
                if isinstance(item, dict) and str(item.get("skill_id") or "").strip()
            }
            for spec, skill_run_id in skill_run_rows:
                snapshot = dict(skill_snapshots_by_id.get(spec.id) or {})
                if not snapshot:
                    snapshot = {
                        "skill_id": spec.id,
                        "skill_version": spec.version,
                        "skill_mode": str(getattr(spec, "mode", "") or "prompt_only"),
                        "execution_mode": str(getattr(spec, "execution_mode_default", "") or "shadow"),
                        "mode_used": str(getattr(spec, "mode", "") or "prompt_only"),
                        "fallback_policy": str(getattr(spec, "fallback_policy", "") or "warn_only"),
                        "fallback_used": False,
                        "fallback_reason": None,
                        "status": "success",
                        "warnings": [],
                        "effective_delta": 0,
                        "findings": [],
                        "evidence": [],
                        "changed_spans": [],
                        "metrics": {},
                        "no_effect_reason": "workflow did not return per-skill details",
                    }
                self.skill_run_repo.succeed(skill_run_id, output_snapshot_json=snapshot)
            step_latency = int((perf_counter() - step_started_at) * 1000)
            logger.info("step done run=%s step=%s key=%s latency=%dms", run_id, step.id, step.step_key, step_latency)
            self.tool_call_repo.succeed(call.id, output_json=output)
            self.agent_run_repo.succeed(agent_run.id, output_json=output)
            if self.evaluation_service is not None and evaluation_run_id is not None:
                self.evaluation_service.record_writing_step(
                    evaluation_run_id=evaluation_run_id,
                    project_id=row.project_id,
                    workflow_run_id=row.id,
                    step_key=str(step.step_key),
                    success=True,
                    latency_ms=step_latency,
                    payload_json={"workflow_type": workflow_type},
                )
        except Exception as exc:
            logger.error("step failed run=%s step=%s key=%s: %s", run_id, step.id, step.step_key, exc, exc_info=True)
            error_payload = {"error": str(exc), "step_key": step.step_key}
            self.workflow_step_repo.fail(step.id, error_code=type(exc).__name__, error_message=str(exc))
            for _, skill_run_id in skill_run_rows:
                self.skill_run_repo.fail(skill_run_id, output_snapshot_json=error_payload)
            self.tool_call_repo.fail(call.id, error_code=type(exc).__name__, output_json=error_payload)
            self.agent_run_repo.fail(agent_run.id, error_code=type(exc).__name__, output_json=error_payload)
            if self.evaluation_service is not None and evaluation_run_id is not None:
                self.evaluation_service.record_writing_step(
                    evaluation_run_id=evaluation_run_id,
                    project_id=row.project_id,
                    workflow_run_id=row.id,
                    step_key=str(step.step_key),
                    success=False,
                    latency_ms=int((perf_counter() - step_started_at) * 1000),
                    payload_json={"error": str(exc), "workflow_type": workflow_type},
                )
            raise

    def _dispatch_step(
        self,
        *,
        row,
        step,
        raw_state: dict[str, dict],
        resolved_skills: list[SkillSpec],
        skill_warnings: list[str],
    ) -> dict[str, Any]:
        step_type = str(step.step_type)
        workflow_type = str((step.input_json or {}).get("workflow_type") or step_type)

        if step_type == "agent":
            return self._run_agent_step(
                row=row,
                step=step,
                raw_state=raw_state,
                resolved_skills=resolved_skills,
                inherited_skill_warnings=skill_warnings,
            )

        if workflow_type == "outline_generation":
            return self._run_outline_step(row=row, step=step, raw_state=raw_state)
        if workflow_type == "chapter_generation":
            return self._run_chapter_step(row=row, step=step, raw_state=raw_state)
        if workflow_type == "consistency_review":
            return self._run_consistency_step(row=row, step=step, raw_state=raw_state)
        if workflow_type == "revision":
            return self._run_revision_step(row=row, step=step, raw_state=raw_state)

        raise RuntimeError(f"未知工作流步骤: {workflow_type}")

    def _run_agent_step(
        self,
        *,
        row,
        step,
        raw_state: dict[str, dict],
        resolved_skills: list[SkillSpec],
        inherited_skill_warnings: list[str],
    ) -> dict[str, Any]:
        role_id = str(step.role_id or step.agent_name or "unknown_agent")
        workflow_type = str((step.input_json or {}).get("workflow_type") or step.step_type)
        role_prompt = "你是写作任务代理，请输出本步骤要点。"
        strategy_temperature = 0.4
        strategy_max_tokens = 8192
        strategy_version = step.strategy_version
        prompt_hash = step.prompt_hash
        schema_version = step.schema_version
        schema_ref = "agents/agent_step_output.schema.json"
        generation_schema: dict[str, Any] | None = None
        skill_warnings: list[str] = list(inherited_skill_warnings or [])
        schema_is_inline = False

        if self.agent_registry is not None:
            profile, strategy, _, warnings = self.agent_registry.resolve(
                role_id=role_id,
                workflow_type=workflow_type,
                step_key=str(step.step_key),
                strategy_mode=(step.input_json or {}).get("strategy_mode"),
            )
            role_prompt = profile.prompt
            strategy_temperature = float(strategy.temperature)
            strategy_max_tokens = int(strategy.max_tokens)
            strategy_version = strategy.version
            schema_version = profile.schema_version
            schema_ref = profile.schema_ref
            prompt_hash = hashlib.sha256(role_prompt.encode("utf-8")).hexdigest()[:16]
            skill_warnings = list(skill_warnings) + [str(item) for item in list(warnings or []) if str(item).strip()]
            skill_warnings.extend(
                [str(item) for item in list(profile.consumption_warnings or []) if str(item).strip()]
            )
            if isinstance(profile.output_schema, dict) and profile.output_schema:
                generation_schema = dict(profile.output_schema)
                schema_is_inline = True
        if self.schema_registry is not None:
            loaded_schema = self.schema_registry.get(schema_ref)
            if isinstance(loaded_schema, dict) and not schema_is_inline:
                generation_schema = loaded_schema

        prompt_payload = self._build_role_prompt_payload(
            row=row,
            step=step,
            raw_state=raw_state,
            role_id=role_id,
        )

        before = self.skill_runtime.run_before_generate(
            skills=list(resolved_skills or []),
            system_prompt=role_prompt,
            input_payload=prompt_payload,
            context=SkillRuntimeContext(
                trace_id=row.trace_id,
                role_id=role_id,
                workflow_type=workflow_type,
                step_key=str(step.step_key),
                mode=str((step.input_json or {}).get("strategy_mode") or ""),
            ),
        )
        self.agent_message_repo.create_message(
            workflow_run_id=row.id,
            workflow_step_id=step.id,
            role="system",
            sender="orchestrator",
            receiver=step.agent_name,
            content=before.system_prompt,
            metadata_json={
                "kind": "prompt",
                "role_id": role_id,
                "strategy_version": strategy_version,
                "prompt_hash": prompt_hash,
                "schema_version": schema_version,
            },
            auto_commit=False,
        )
        self.agent_message_repo.create_message(
            workflow_run_id=row.id,
            workflow_step_id=step.id,
            role="user",
            sender="orchestrator",
            receiver=step.agent_name,
            content=json.dumps(before.input_payload, ensure_ascii=False),
            metadata_json={"kind": "input"},
            auto_commit=False,
        )
        self.agent_message_repo.db.commit()

        result = self.text_provider.generate(
            TextGenerationRequest(
                system_prompt=before.system_prompt,
                user_prompt=json.dumps(before.input_payload, ensure_ascii=False),
                temperature=strategy_temperature,
                max_tokens=strategy_max_tokens,
                input_payload=before.input_payload,
                input_schema=self.AGENT_STEP_INPUT_SCHEMA,
                input_schema_name=f"{role_id}_{str(step.step_key)}_input",
                input_schema_strict=True,
                response_schema=generation_schema,
                response_schema_name=f"{role_id}_{str(step.step_key)}_output",
                response_schema_strict=True,
                validation_retries=1,
                use_function_calling=bool(generation_schema),
                function_name=f"{role_id}_{str(step.step_key)}_output",
                function_description="Return agent step output JSON that matches schema.",
                metadata_json={
                    "workflow": "agent_step",
                    "workflow_type": workflow_type,
                    "step_key": step.step_key,
                    "trace_id": row.trace_id,
                    "workflow_run_id": str(row.id),
                    "workflow_step_id": str(step.id),
                    "role_id": role_id,
                    "strategy_version": strategy_version,
                    "prompt_hash": prompt_hash,
                },
            )
        )

        after = self.skill_runtime.run_after_generate(
            skills=list(resolved_skills or []),
            output_payload=dict(result.json_data or {}),
            context=SkillRuntimeContext(
                trace_id=row.trace_id,
                role_id=role_id,
                workflow_type=workflow_type,
                step_key=str(step.step_key),
                mode=str((step.input_json or {}).get("strategy_mode") or ""),
            ),
        )
        view_payload = dict(after.output_payload or {})
        notes = self._build_agent_notes(
            role_id=role_id,
            agent_output=view_payload,
            fallback_text=str(result.text or "").strip(),
        )
        all_warnings = []
        all_warnings.extend([str(item) for item in list(skill_warnings or []) if str(item).strip()])
        all_warnings.extend([str(item) for item in list(before.warnings or []) if str(item).strip()])
        all_warnings.extend([str(item) for item in list(after.warnings or []) if str(item).strip()])
        skill_runs = self._serialize_skill_runtime_runs(
            skills=list(resolved_skills or []),
            before_runs=list(before.runs or []),
            after_runs=list(after.runs or []),
        )
        step_meta, step_raw = build_agent_step_meta_raw(
            result=result,
            schema_ref=schema_ref,
            schema_version=schema_version,
            prompt_hash=prompt_hash,
            strategy_version=strategy_version,
            skills_executed_count=len(skill_runs),
        )
        output = {
            "step_key": step.step_key,
            "agent_name": step.agent_name,
            "role_id": role_id,
            "strategy_version": strategy_version,
            "prompt_hash": prompt_hash,
            "schema_version": schema_version,
            "schema_ref": schema_ref,
            "view": view_payload,
            "meta": step_meta,
            "raw": step_raw,
            "agent_output": view_payload,
            "notes": notes,
            "mock_mode": bool(result.is_mock),
            "warnings": all_warnings,
            "skills_executed_count": len(skill_runs),
            "skills_effective_delta": int(sum(int(item.get("effective_delta") or 0) for item in skill_runs)),
            "skill_runs": skill_runs,
        }
        if str(role_id or "").strip().lower() == "planner_agent":
            output["knowledge_plan_meta"] = planner_knowledge_meta(view_payload)
        if self.schema_registry is not None:
            if schema_is_inline and isinstance(generation_schema, dict) and generation_schema:
                validation_warnings = self.schema_registry.validate_inline(
                    schema=generation_schema,
                    payload=view_payload,
                    strict=self.runtime_config.schema_strict,
                    degrade_mode=self.runtime_config.schema_degrade_mode,
                )
            elif not schema_is_inline:
                validation_warnings = self.schema_registry.validate(
                    schema_ref=schema_ref,
                    payload=view_payload,
                    strict=self.runtime_config.schema_strict,
                    degrade_mode=self.runtime_config.schema_degrade_mode,
                )
            else:
                validation_warnings = []
            if validation_warnings:
                output["warnings"] = list(output.get("warnings") or []) + validation_warnings

        self.agent_message_repo.create_message(
            workflow_run_id=row.id,
            workflow_step_id=step.id,
            role="assistant",
            sender=step.agent_name,
            receiver="orchestrator",
            content=output["notes"],
            metadata_json={
                "kind": "output",
                "provider": result.provider,
                "model": result.model,
                "role_id": role_id,
                "strategy_version": strategy_version,
                "prompt_hash": prompt_hash,
                "schema_version": schema_version,
            },
        )

        self._apply_story_asset_mutations(
            project_id=row.project_id,
            notes=notes,
            agent_output=view_payload,
            role_id=role_id,
        )
        return output

    @staticmethod
    def _serialize_skill_runtime_runs(
        *,
        skills: list[SkillSpec],
        before_runs: list[Any],
        after_runs: list[Any],
    ) -> list[dict[str, Any]]:
        all_runs = list(before_runs) + list(after_runs)
        payloads: list[dict[str, Any]] = []
        for spec in list(skills or []):
            matched = [item for item in all_runs if str(getattr(item, "skill_id", "")) == spec.id]
            statuses = [str(getattr(item, "status", "") or "").strip().lower() for item in matched]
            if any(status == "failed" for status in statuses):
                status = "failed"
            elif all(status == "skipped" for status in statuses) and statuses:
                status = "skipped"
            else:
                status = "success"
            execution_mode = next(
                (
                    str(getattr(item, "execution_mode", "")).strip()
                    for item in matched
                    if str(getattr(item, "execution_mode", "")).strip()
                ),
                str(getattr(spec, "execution_mode_default", "") or "shadow"),
            )
            mode_used = next(
                (
                    str(getattr(item, "mode_used", "")).strip()
                    for item in matched
                    if str(getattr(item, "mode_used", "")).strip()
                ),
                str(getattr(spec, "mode", "") or "prompt_only"),
            )
            payloads.append(
                {
                    "skill_id": spec.id,
                    "skill_version": spec.version,
                    "skill_mode": str(getattr(spec, "mode", "") or "prompt_only"),
                    "execution_mode": execution_mode,
                    "mode_used": mode_used,
                    "fallback_policy": str(getattr(spec, "fallback_policy", "") or "warn_only"),
                    "fallback_used": any(bool(getattr(item, "fallback_used", False)) for item in matched),
                    "fallback_reason": next(
                        (
                            str(getattr(item, "fallback_reason", "")).strip()
                            for item in matched
                            if str(getattr(item, "fallback_reason", "")).strip()
                        ),
                        None,
                    ),
                    "status": status,
                    "effective_delta": int(
                        sum(int(getattr(item, "effective_delta", 0) or 0) for item in matched)
                    ),
                    "warnings": [
                        str(w)
                        for item in matched
                        for w in list(getattr(item, "warnings", []) or [])
                        if str(w).strip()
                    ],
                    "findings": [
                        dict(v)
                        for item in matched
                        for v in list(getattr(item, "findings", []) or [])
                        if isinstance(v, dict)
                    ],
                    "evidence": [
                        dict(v)
                        for item in matched
                        for v in list(getattr(item, "evidence", []) or [])
                        if isinstance(v, dict)
                    ],
                    "changed_spans": [
                        dict(v)
                        for item in matched
                        for v in list(getattr(item, "changed_spans", []) or [])
                        if isinstance(v, dict)
                    ],
                    "metrics": {
                        key: value
                        for item in matched
                        for key, value in dict(getattr(item, "metrics", {}) or {}).items()
                    },
                    "no_effect_reason": next(
                        (
                            str(getattr(item, "no_effect_reason", "")).strip()
                            for item in matched
                            if str(getattr(item, "no_effect_reason", "")).strip()
                        ),
                        None,
                    ),
                    "phases": [
                        {
                            "phase": str(getattr(item, "phase", "")),
                            "status": str(getattr(item, "status", "")),
                            "applied": bool(getattr(item, "applied", False)),
                            "effective_delta": int(getattr(item, "effective_delta", 0) or 0),
                            "execution_mode": str(getattr(item, "execution_mode", "") or execution_mode),
                            "mode_used": str(getattr(item, "mode_used", "") or mode_used),
                            "fallback_used": bool(getattr(item, "fallback_used", False)),
                            "fallback_reason": str(getattr(item, "fallback_reason", "") or "").strip() or None,
                            "metrics": dict(getattr(item, "metrics", {}) or {}),
                            "no_effect_reason": str(getattr(item, "no_effect_reason", "") or "").strip() or None,
                        }
                        for item in matched
                    ],
                }
            )
        return payloads

    def _apply_story_asset_mutations(
        self,
        *,
        project_id: str,
        notes: str,
        agent_output: dict[str, Any],
        role_id: str,
    ) -> None:
        """解析 agent 输出中的故事资产变更标签并写入数据库。"""
        import re

        if not notes:
            return
        if not hasattr(self, "_character_repo") or not hasattr(self, "_timeline_repo"):
            return
        try:
            new_chars = re.findall(
                r"\[NEW_CHARACTER\]\s*名称[：:]\s*(.+?)\s*\|\s*类型[：:]\s*(.+?)\s*\|\s*描述[：:]\s*(.+)",
                notes,
            )
            for name, role_type, description in new_chars:
                self._character_repo.create(
                    project_id=project_id,
                    name=name.strip(),
                    role_type=role_type.strip(),
                )
                logger.info("auto-created character %s for project %s", name.strip(), project_id)

            timeline_events = re.findall(
                r"\[UPDATE_TIMELINE\]\s*事件[：:]\s*(.+?)\s*\|\s*章节[：:]\s*(\d+)",
                notes,
            )
            for title, chapter_no in timeline_events:
                self._timeline_repo.create(
                    project_id=project_id,
                    event_title=title.strip(),
                    chapter_no=int(chapter_no),
                )
                logger.info("auto-created timeline event '%s' ch%s for project %s", title.strip(), chapter_no, project_id)
        except Exception:
            logger.warning("故事资产自动变更失败", exc_info=True)

    def _build_agent_notes(
        self,
        *,
        role_id: str,
        agent_output: dict[str, Any],
        fallback_text: str,
    ) -> str:
        rid = str(role_id or "").strip().lower()
        if rid == "character_agent":
            constraints = dict(agent_output.get("constraints") or {})
            must_do = [str(x).strip() for x in list(constraints.get("must_do") or []) if str(x).strip()]
            must_not = [str(x).strip() for x in list(constraints.get("must_not") or []) if str(x).strip()]
            bits: list[str] = []
            if must_do:
                bits.append("角色必须执行: " + "；".join(must_do[:4]))
            if must_not:
                bits.append("角色禁止行为: " + "；".join(must_not[:4]))
            return " | ".join(bits) or fallback_text
        if rid == "world_agent":
            rules = [dict(x) for x in list(agent_output.get("hard_constraints") or []) if isinstance(x, dict)]
            if rules:
                preview = [
                    f"{str(x.get('rule_type') or 'rule').upper()}:{str(x.get('rule_description') or '').strip()}（限制:{str(x.get('limitation') or '').strip()}）"
                    for x in rules[:3]
                ]
                preview = [x for x in preview if x.strip()]
                if preview:
                    return "世界硬约束: " + "；".join(preview)
            return fallback_text
        if rid == "style_agent":
            micro = dict(agent_output.get("micro_constraints") or {})
            sent = str(micro.get("sentence_structure") or "").strip()
            vocab = str(micro.get("vocabulary_level") or "").strip()
            forbidden = [str(x).strip() for x in list(micro.get("forbidden_words") or []) if str(x).strip()]
            parts = []
            if sent:
                parts.append(f"句式:{sent}")
            if vocab:
                parts.append(f"词汇:{vocab}")
            if forbidden:
                parts.append("禁词:" + "、".join(forbidden[:8]))
            return " | ".join(parts) or fallback_text
        if rid == "retrieval_agent":
            summary = dict(agent_output.get("writing_context_summary") or {})
            facts = [str(x).strip() for x in list(summary.get("key_facts") or []) if str(x).strip()]
            if facts:
                return "关键事实: " + "；".join(facts[:6])
            return fallback_text
        if rid == "plot_agent":
            goal = str(agent_output.get("chapter_goal") or "").strip()
            conflict = str(agent_output.get("core_conflict") or "").strip()
            parts = [x for x in [goal, conflict] if x]
            return " | ".join(parts) or fallback_text
        if rid == "planner_agent":
            return str(agent_output.get("plan_summary") or "").strip() or fallback_text
        return fallback_text

    def _build_role_prompt_payload(
        self,
        *,
        row,
        step,
        raw_state: dict[str, dict],
        role_id: str,
    ) -> dict[str, Any]:
        workflow_type = str((step.input_json or {}).get("workflow_type") or step.step_type)
        project = self.project_repo.get(row.project_id)
        project_context = {
            "id": str(row.project_id),
            "title": getattr(project, "title", None),
            "genre": getattr(project, "genre", None),
            "premise": getattr(project, "premise", None),
            "metadata_json": getattr(project, "metadata_json", None) or {},
        }
        outline_state = dict(raw_state.get("outline_generation") or {})
        outline_structure = outline_state.get("structure_json")
        if not isinstance(outline_structure, dict):
            outline_structure = {}

        story_state_snapshot: dict[str, Any] | None = None
        if self.story_state_snapshot_repo is not None:
            ch_raw = (row.input_json or {}).get("chapter_no")
            if ch_raw is not None:
                try:
                    ch_no = int(ch_raw)
                except (TypeError, ValueError):
                    ch_no = None
                if ch_no is not None:
                    snap = self.story_state_snapshot_repo.get_latest_before(
                        project_id=row.project_id,
                        before_chapter_no=ch_no,
                    )
                    if snap is not None:
                        st = dict(snap.state_json or {})
                        story_state_snapshot = {
                            "after_chapter_no": int(snap.chapter_no),
                            "source": snap.source,
                            "location": st.get("location"),
                            "party": st.get("party"),
                            "relationships": st.get("relationships"),
                            "knowledge": st.get("knowledge"),
                            "identity_exposure": st.get("identity_exposure"),
                            "state": st,
                        }

        retrieval_bundle = build_retrieval_bundle_from_raw_state(raw_state)
        wn_raw = (row.input_json or {}).get("working_notes")
        working_notes_arg = wn_raw if isinstance(wn_raw, (list, dict)) else None

        core = self.prompt_payload_assembler.build(
            role_id=role_id,
            step_key=str(step.step_key),
            workflow_type=workflow_type,
            project_context=project_context,
            raw_state=raw_state,
            retrieval_bundle=retrieval_bundle,
            outline_state=outline_state,
            working_notes=working_notes_arg,
        )

        retrieval_view = dict(core.get("retrieval") or {})
        key_facts = [str(x).strip() for x in list(retrieval_view.get("key_facts") or []) if str(x).strip()]
        current_states = [
            str(x).strip()
            for x in list(retrieval_view.get("current_states") or [])
            if str(x).strip()
        ]

        base_payload = {
            **core,
            "goal": (row.input_json or {}).get("writing_goal"),
            "local_data_tools": (
                self.agent_registry.local_data_tools_catalog()
                if self.agent_registry is not None
                else []
            ),
            "retrieval_summary": {
                "key_facts": key_facts,
                "current_states": current_states,
            },
        }
        if story_state_snapshot is not None:
            base_payload["story_state_snapshot"] = story_state_snapshot
        rid = str(role_id or "").strip().lower()
        if rid == "character_agent":
            return {
                **base_payload,
                "Role_Profile": {
                    "character_arcs": list(outline_structure.get("character_arcs") or []),
                    "key_facts": key_facts,
                },
                "Story_Background": {
                    "project": project_context,
                    "outline_title": outline_state.get("title"),
                },
                "Current_Chapter": {
                    "goal": (row.input_json or {}).get("writing_goal"),
                    "chapter_no": (row.input_json or {}).get("chapter_no"),
                    "signals": current_states,
                },
            }
        if rid == "world_agent":
            return {
                **base_payload,
                "world_context": {
                    "premise": project_context.get("premise"),
                    "facts": key_facts,
                    "outline": outline_structure,
                },
            }
        if rid == "style_agent":
            return {
                **base_payload,
                "style_context": {
                    "style_hint": (row.input_json or {}).get("style_hint"),
                    "genre": project_context.get("genre"),
                },
            }
        if rid == "plot_agent":
            return {
                **base_payload,
                "plot_context": {
                    "chapter_no": (row.input_json or {}).get("chapter_no"),
                    "target_words": (row.input_json or {}).get("target_words"),
                },
            }
        return base_payload

    def _run_outline_step(self, *, row, step, raw_state: dict[str, dict]) -> dict[str, Any]:
        base_goal = str((row.input_json or {}).get("writing_goal") or "")
        retrieval = self._run_retrieval_loop(
            row=row,
            step=step,
            workflow_type="outline_generation",
            writing_goal=base_goal,
            chapter_no=(row.input_json or {}).get("chapter_no"),
            raw_state=raw_state,
        )
        effective_goal = base_goal
        if retrieval.context_text:
            effective_goal = f"{base_goal}\n\n可用证据：\n{retrieval.context_text}"
        result = self.outline_service.run(
            OutlineGenerationRequest(
                project_id=row.project_id,
                writing_goal=effective_goal,
                style_hint=(row.input_json or {}).get("style_hint"),
                request_id=row.request_id,
                trace_id=row.trace_id,
                retrieval_context=retrieval.context_text or None,
            )
        )
        return {
            "outline_id": result.outline_id,
            "version_no": result.version_no,
            "title": result.title,
            "content": result.content,
            "structure_json": dict(result.structure_json or {}),
            "mock_mode": result.mock_mode,
            "strategy_mode": (step.input_json or {}).get("strategy_mode"),
            **self._serialize_retrieval_summary(retrieval),
        }

    def _run_chapter_step(self, *, row, step, raw_state: dict[str, dict]) -> dict[str, Any]:
        outline_title = str(raw_state.get("outline_generation", {}).get("title") or "")
        base_goal = str((row.input_json or {}).get("writing_goal") or "")
        goal = base_goal if not outline_title else f"{base_goal}；参考大纲：{outline_title}"

        retrieval = self._run_retrieval_loop(
            row=row,
            step=step,
            workflow_type="chapter_generation",
            writing_goal=goal,
            chapter_no=(row.input_json or {}).get("chapter_no"),
            raw_state=raw_state,
        )
        combined_retrieval_context = str(retrieval.context_text or "").strip() or None

        working_notes = [
            str(x).strip() for x in list((row.input_json or {}).get("working_notes") or []) if str(x).strip()
        ]
        style_hint = str((row.input_json or {}).get("style_hint") or "").strip() or None

        chapter_raw_snapshot: dict[str, Any] = {
            k: dict(v) if isinstance(v, dict) else v for k, v in raw_state.items()
        }

        def _writer_live_progress(payload: dict[str, Any]) -> None:
            try:
                if not payload or str(payload.get("kind") or "").lower() == "idle":
                    self.workflow_step_repo.merge_live_progress(
                        step_id=step.id,
                        live_progress=None,
                        lease_extend_seconds=self.runtime_config.run_lease_extend_seconds,
                        worker_id=self.runtime_config.worker_instance_id,
                    )
                else:
                    self.workflow_step_repo.merge_live_progress(
                        step_id=step.id,
                        live_progress=payload,
                        lease_extend_seconds=self.runtime_config.run_lease_extend_seconds,
                        worker_id=self.runtime_config.worker_instance_id,
                    )
            except Exception:
                logger.debug("writer live_progress 写入步骤失败 step_id=%s", step.id, exc_info=True)

        def _writer_checkpoint(payload: dict[str, Any]) -> None:
            try:
                self.workflow_step_repo.merge_checkpoint(step_id=step.id, checkpoint=payload)
                self.workflow_run_repo.touch_execution_lease(
                    row.id,
                    worker_id=self.runtime_config.worker_instance_id,
                    extend_seconds=self.runtime_config.run_lease_extend_seconds,
                )
            except Exception:
                logger.debug("writer checkpoint 写入步骤失败 step_id=%s", step.id, exc_info=True)

        result = self.chapter_tool.run(
            ChapterGenerationRequest(
                project_id=row.project_id,
                writing_goal=goal,
                chapter_no=(row.input_json or {}).get("chapter_no"),
                target_words=int((row.input_json or {}).get("target_words") or 1200),
                style_hint=style_hint,
                include_memory_top_k=int((row.input_json or {}).get("include_memory_top_k") or 8),
                context_token_budget=(
                    int((row.input_json or {}).get("context_token_budget"))
                    if (row.input_json or {}).get("context_token_budget") is not None
                    else None
                ),
                temperature=float((row.input_json or {}).get("temperature") or 0.7),
                chat_turns=list((row.input_json or {}).get("chat_turns") or []),
                working_notes=working_notes or None,
                persist_chapter=False,
                enforce_chapter_word_count=_coerce_enforce_chapter_word_count(
                    (row.input_json or {}).get("enforce_chapter_word_count"),
                ),
                request_id=row.request_id,
                trace_id=row.trace_id,
                retrieval_context=combined_retrieval_context,
                orchestrator_raw_state=chapter_raw_snapshot,
                live_progress_callback=_writer_live_progress,
                checkpoint_callback=_writer_checkpoint,
            )
        )
        chapter = dict(result.chapter or {})
        _chapter_repo = self.chapter_tool.workflow_service.chapter_repo
        raw_chapter_no = (
            chapter.get("chapter_no")
            or (row.input_json or {}).get("chapter_no")
        )
        if raw_chapter_no is not None:
            try:
                chapter_no = int(raw_chapter_no)
            except (TypeError, ValueError):
                chapter_no = _chapter_repo.get_next_chapter_no(row.project_id)
        else:
            chapter_no = _chapter_repo.get_next_chapter_no(row.project_id)
        expire_at = datetime.now(tz=timezone.utc) + timedelta(hours=max(1, int(self.runtime_config.review_expire_hours)))
        candidate = self.chapter_candidate_repo.create_candidate(
            project_id=row.project_id,
            workflow_run_id=row.id,
            workflow_step_id=step.id,
            agent_run_id=result.agent_run_id,
            chapter_no=chapter_no,
            title=chapter.get("title"),
            content=str(chapter.get("content") or ""),
            summary=chapter.get("summary"),
            expires_at=expire_at,
            idempotency_key=f"{row.id}:{step.step_key}:candidate",
            trace_id=row.trace_id,
            request_id=row.request_id,
            metadata_json={
                "strategy_mode": (step.input_json or {}).get("strategy_mode"),
                "mock_mode": bool(result.mock_mode),
            },
        )
        self.workflow_run_repo.mark_waiting_review(row.id)
        meta_llm: dict[str, Any] = {}
        lm = result.llm_request_metadata
        if isinstance(lm, dict):
            tid = lm.get("llm_task_id")
            if tid:
                meta_llm["llm_task_id"] = str(tid)
            tidp = lm.get("llm_task_id_prior")
            if tidp:
                meta_llm["llm_task_id_prior"] = str(tidp)
        if self.webhook_service is not None:
            try:
                self.webhook_service.enqueue_event(
                    project_id=row.project_id,
                    event_type="chapter.candidate.created",
                    payload_json={
                        "run_id": str(row.id),
                        "candidate_id": str(candidate.id),
                        "chapter_no": chapter_no,
                        "expires_at": expire_at.isoformat().replace("+00:00", "Z"),
                        "trace_id": row.trace_id,
                    },
                    trace_id=row.trace_id,
                    request_id=row.request_id,
                )
                self.webhook_service.enqueue_event(
                    project_id=row.project_id,
                    event_type="writing.run.waiting_review",
                    payload_json={
                        "run_id": str(row.id),
                        "candidate_id": str(candidate.id),
                        "trace_id": row.trace_id,
                    },
                    trace_id=row.trace_id,
                    request_id=row.request_id,
                )
            except Exception:
                pass
        return {
            "chapter": chapter,
            "memory_ingestion": dict(result.memory_ingestion),
            "agent_run_id": result.agent_run_id,
            "mock_mode": bool(result.mock_mode),
            "writer_structured": dict(result.writer_structured or {}) if result.writer_structured else None,
            "warnings": [str(item) for item in list(result.warnings or []) if str(item).strip()],
            "skill_runs": list(result.skill_runs or []),
            "skills_executed_count": len(list(result.skill_runs or [])),
            "skills_effective_delta": int(
                sum(int(item.get("effective_delta") or 0) for item in list(result.skill_runs or []))
            ),
            "candidate": {
                "id": str(candidate.id),
                "status": str(candidate.status),
                "chapter_no": int(candidate.chapter_no),
                "expires_at": candidate.expires_at.isoformat().replace("+00:00", "Z")
                if candidate.expires_at is not None
                else None,
            },
            "waiting_review": True,
            "strategy_mode": (step.input_json or {}).get("strategy_mode"),
            "meta": meta_llm,
            "writer_guidance": {
                "style_hint": style_hint or None,
                "working_notes_count": len(working_notes),
                "prompt_payload_via_assembler": True,
                # 兼容旧前端：Markdown 护栏已弃用，章节草稿上下文见 Assembler 分区 JSON
                "has_guidance_text": False,
            },
            **self._serialize_retrieval_summary(retrieval),
        }

    def _run_consistency_step(self, *, row, step, raw_state: dict[str, dict]) -> dict[str, Any]:
        chapter = dict(
            raw_state.get("writer_draft", {}).get("chapter")
            or raw_state.get("chapter_generation", {}).get("chapter")
            or {}
        )
        chapter_id = chapter.get("id")
        if not chapter_id:
            raise RuntimeError("consistency_review 缺少 chapter_id")

        chapter_summary = str(chapter.get("summary") or chapter.get("content") or "")[:600]
        retrieval = self._run_retrieval_loop(
            row=row,
            step=step,
            workflow_type="consistency_review",
            writing_goal=f"一致性审查：{chapter_summary}",
            chapter_no=chapter.get("chapter_no") or (row.input_json or {}).get("chapter_no"),
            must_have_slots=["character", "world_rule", "timeline", "foreshadowing", "conflict_evidence"],
            raw_state=raw_state,
        )

        role_id = str(step.role_id or step.agent_name or "consistency_agent")
        llm_prompt: str | None = None
        llm_temperature: float | None = None
        llm_max_tokens: int | None = None
        llm_schema: dict[str, Any] | None = None
        llm_schema_ref: str | None = None
        llm_strategy_version: str | None = step.strategy_version
        llm_prompt_hash: str | None = step.prompt_hash
        warnings: list[str] = []

        if self.agent_registry is not None:
            profile, strategy, _, warnings = self.agent_registry.resolve(
                role_id=role_id,
                workflow_type="consistency_review",
                step_key=str(step.step_key),
                strategy_mode=(step.input_json or {}).get("strategy_mode"),
            )
            warnings = list(warnings) + [
                str(item) for item in list(profile.consumption_warnings or []) if str(item).strip()
            ]
            llm_prompt = profile.prompt
            llm_temperature = float(strategy.temperature)
            llm_max_tokens = int(strategy.max_tokens)
            llm_schema_ref = profile.schema_ref
            llm_strategy_version = strategy.version
            llm_prompt_hash = hashlib.sha256(llm_prompt.encode("utf-8")).hexdigest()[:16]
            if isinstance(profile.output_schema, dict) and profile.output_schema:
                llm_schema = dict(profile.output_schema)
            elif self.schema_registry is not None:
                loaded = self.schema_registry.get(profile.schema_ref)
                if isinstance(loaded, dict):
                    llm_schema = loaded

        proj_row = self.project_repo.get(row.project_id)
        project_snapshot: dict[str, Any] = {"id": str(row.project_id)}
        if proj_row is not None:
            project_snapshot = {
                "id": str(proj_row.id),
                "title": getattr(proj_row, "title", None),
                "genre": getattr(proj_row, "genre", None),
                "premise": getattr(proj_row, "premise", None),
                "metadata_json": getattr(proj_row, "metadata_json", None) or {},
            }

        result = self.consistency_service.run(
            ConsistencyReviewRequest(
                project_id=row.project_id,
                chapter_id=chapter_id,
                chapter_version_id=chapter.get("version_id"),
                trace_id=row.trace_id,
                retrieval_bundle=dict(retrieval.context_bundle or {}),
                project_snapshot=project_snapshot,
                llm_enabled=True,
                llm_system_prompt=llm_prompt,
                llm_temperature=llm_temperature,
                llm_max_tokens=llm_max_tokens,
                llm_response_schema=llm_schema,
                llm_schema_ref=llm_schema_ref,
                llm_role_id=role_id,
                llm_strategy_version=llm_strategy_version,
                llm_prompt_hash=llm_prompt_hash,
            )
        )
        return {
            "report_id": result.report_id,
            "status": result.status,
            "score": result.score,
            "summary": result.summary,
            "issues": result.issues,
            "recommendations": result.recommendations,
            "llm_used": bool(result.llm_used),
            "rule_issues_count": int(result.rule_issues_count),
            "llm_issues_count": int(result.llm_issues_count),
            "warnings": list(warnings),
            "strategy_mode": (step.input_json or {}).get("strategy_mode"),
            **self._serialize_retrieval_summary(retrieval),
        }

    def _run_revision_step(self, *, row, step, raw_state: dict[str, dict]) -> dict[str, Any]:
        chapter = dict(
            raw_state.get("writer_draft", {}).get("chapter")
            or raw_state.get("chapter_generation", {}).get("chapter")
            or {}
        )
        chapter_id = chapter.get("id")
        if not chapter_id:
            raise RuntimeError("revision 缺少 chapter_id")

        consistency = dict(raw_state.get("consistency_review", {}) or {})
        force = str(consistency.get("status") or "warning") in {"warning", "failed"}
        alignment_supplement = build_writer_alignment_supplement_text(raw_state)
        retrieval = self._run_retrieval_loop(
            row=row,
            step=step,
            workflow_type="revision",
            writing_goal=(
                f"根据一致性报告修订章节。"
                f"报告摘要：{str(consistency.get('summary') or '')}"
            ),
            chapter_no=chapter.get("chapter_no") or (row.input_json or {}).get("chapter_no"),
            must_have_slots=[
                "character",
                "world_rule",
                "timeline",
                "foreshadowing",
                "conflict_evidence",
                "chapter_neighborhood",
            ],
            raw_state=raw_state,
        )

        retrieval_bundle = copy.deepcopy(dict(retrieval.context_bundle or {}))
        summary = dict(retrieval_bundle.get("summary") or {})
        key_facts = list(summary.get("key_facts") or [])
        if alignment_supplement:
            sup = str(alignment_supplement).strip()
            if sup:
                key_facts.insert(0, sup[:12000])
        retrieval_bundle["summary"] = {**summary, "key_facts": key_facts}

        project = self.project_repo.get(row.project_id)
        project_context = {
            "id": str(row.project_id),
            "title": getattr(project, "title", None),
            "genre": getattr(project, "genre", None),
            "premise": getattr(project, "premise", None),
            "metadata_json": getattr(project, "metadata_json", None) or {},
        }
        wn_raw = (row.input_json or {}).get("working_notes")
        working_notes_arg = wn_raw if isinstance(wn_raw, (list, dict)) else None

        orch_snapshot: dict[str, Any] = {}
        for k, v in raw_state.items():
            if isinstance(v, dict):
                orch_snapshot[str(k)] = copy.deepcopy(v)

        result = self.revision_service.run(
            RevisionRequest(
                project_id=row.project_id,
                chapter_id=chapter_id,
                trace_id=row.trace_id,
                force=force,
                retrieval_bundle=retrieval_bundle,
                orchestrator_raw_state=orch_snapshot,
                project_context=project_context,
                working_notes=working_notes_arg,
            )
        )
        return {
            "revised": result.revised,
            "chapter_id": result.chapter_id,
            "version_id": result.version_id,
            "issues_count": result.issues_count,
            "mock_mode": result.mock_mode,
            "writer_structured": dict(result.writer_structured or {}) if result.writer_structured else None,
            "warnings": [str(item) for item in list(result.warnings or []) if str(item).strip()],
            "skill_runs": list(result.skill_runs or []),
            "skills_executed_count": len(list(result.skill_runs or [])),
            "skills_effective_delta": int(
                sum(int(item.get("effective_delta") or 0) for item in list(result.skill_runs or []))
            ),
            "strategy_mode": (step.input_json or {}).get("strategy_mode"),
            **self._serialize_retrieval_summary(retrieval),
        }

    @staticmethod
    def _planner_slot_hints_from_state(
        raw_state: dict[str, dict] | None,
        step_input: dict[str, Any] | None,
    ) -> list[str]:
        """合并 planner_bootstrap 与当前步骤 input 中的 plan_required_slots。"""
        bootstrap: dict[str, Any] | None = None
        if raw_state:
            b = raw_state.get("planner_bootstrap")
            if isinstance(b, dict):
                bootstrap = b
        return merge_planner_retrieval_slots(
            planner_bootstrap_output=bootstrap,
            step_input=step_input,
        )

    @staticmethod
    def _planner_verify_facts_from_state(
        raw_state: dict[str, dict] | None,
        step_input: dict[str, Any] | None,
    ) -> list[str]:
        bootstrap: dict[str, Any] | None = None
        if raw_state:
            b = raw_state.get("planner_bootstrap")
            if isinstance(b, dict):
                bootstrap = b
        return merge_planner_verify_facts(
            planner_bootstrap_output=bootstrap,
            step_input=step_input,
        )

    @staticmethod
    def _planner_preferred_tools_from_state(
        raw_state: dict[str, dict] | None,
        step_input: dict[str, Any] | None,
    ) -> list[str]:
        bootstrap: dict[str, Any] | None = None
        if raw_state:
            b = raw_state.get("planner_bootstrap")
            if isinstance(b, dict):
                bootstrap = b
        return merge_planner_preferred_tools(
            planner_bootstrap_output=bootstrap,
            step_input=step_input,
        )

    def _run_retrieval_loop(
        self,
        *,
        row,
        step,
        workflow_type: str,
        writing_goal: str,
        chapter_no: int | None = None,
        must_have_slots: list[str] | None = None,
        raw_state: dict[str, dict] | None = None,
    ) -> RetrievalLoopSummary:
        if self.retrieval_loop is None:
            disabled_bundle: dict[str, Any] = {
                "summary": {
                    "key_facts": [],
                    "current_states": [],
                    "confirmed_facts": [],
                    "supporting_evidence": [],
                    "conflicts": [],
                    "information_gaps": [],
                },
                "items": [],
                "meta": {},
            }
            mirror_context_bundle_lists_from_summary(disabled_bundle)
            return RetrievalLoopSummary(
                retrieval_trace_id=f"{row.trace_id}:{step.step_key}:disabled",
                context_bundle=disabled_bundle,
            )
        step_inp = dict(step.input_json or {}) if step is not None else {}
        planner_hints = self._planner_slot_hints_from_state(raw_state, step_inp)
        verify_facts = self._planner_verify_facts_from_state(raw_state, step_inp)
        preferred_tools = self._planner_preferred_tools_from_state(raw_state, step_inp)
        relevance_blob = RetrievalLoopService.build_relevance_blob(
            writing_goal=writing_goal,
            planner_slots=planner_hints,
            verify_facts=verify_facts,
        )
        ri = dict(row.input_json or {})
        meta = ri.get("metadata_json") if isinstance(ri.get("metadata_json"), dict) else {}
        fc = ri.get("focus_character_id") or meta.get("focus_character_id")
        focus_character_id = str(fc).strip() if fc else None
        return self.retrieval_loop.run(
            RetrievalLoopRequest(
                workflow_run_id=row.id,
                workflow_step_id=step.id,
                project_id=row.project_id,
                trace_id=row.trace_id,
                step_key=str(step.step_key),
                workflow_type=workflow_type,
                writing_goal=writing_goal,
                chapter_no=(int(chapter_no) if chapter_no is not None else None),
                user_id=row.initiated_by,
                planner_slot_hints=planner_hints or None,
                must_have_slots=must_have_slots,
                relevance_blob=relevance_blob,
                planner_verify_facts=verify_facts or None,
                planner_preferred_tools=preferred_tools or None,
                focus_character_id=focus_character_id,
            )
        )

    @staticmethod
    def _serialize_retrieval_summary(summary: RetrievalLoopSummary) -> dict[str, Any]:
        meta_cb = dict((summary.context_bundle or {}).get("meta") or {})
        return {
            "retrieval_trace_id": summary.retrieval_trace_id,
            "planner_preferred_tools": list(meta_cb.get("planner_preferred_tools") or []),
            "retrieval_rounds": [
                {
                    "round_index": int(item.round_index),
                    "query": item.decision.query,
                    "intent": item.decision.intent,
                    "source_types": list(item.decision.source_types),
                    "must_have_slots": list(item.decision.must_have_slots),
                    "slot_query_fragments": dict(item.decision.slot_query_fragments or {}),
                    "coverage_score": float(item.coverage.coverage_score),
                    "resolved_slots": list(item.coverage.resolved_slots),
                    "open_slots": list(item.coverage.open_slots),
                    "new_evidence_gain": float(item.new_evidence_gain),
                    "stop_reason": item.coverage.stop_reason,
                    "latency_ms": int(item.latency_ms) if item.latency_ms is not None else None,
                }
                for item in list(summary.rounds or [])
            ],
            "retrieval_stop_reason": summary.stop_reason,
            "evidence_coverage": float(summary.coverage.coverage_score),
            "open_slots": list(summary.coverage.open_slots),
            "context_budget_usage": dict(summary.context_budget_usage or {}),
            "retrieval_context_bundle": dict(summary.context_bundle or {}),
        }

    def _build_state(self, run_id) -> dict[str, dict]:
        steps = self.workflow_step_repo.list_by_run(workflow_run_id=run_id)
        raw_state: dict[str, dict] = {}
        for step in steps:
            if str(step.status) == "success":
                raw_state[str(step.step_key)] = dict(step.output_json or {})
        return raw_state

    @staticmethod
    def _plan_to_json(plan: PlannerPlan) -> dict[str, Any]:
        return {
            "plan_version": plan.plan_version,
            "nodes": [asdict(node) for node in plan.nodes],
            "retry_policy": dict(plan.retry_policy or {}),
            "fallback_policy": dict(plan.fallback_policy or {}),
            "planned_at": datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        }
