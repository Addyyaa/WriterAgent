from __future__ import annotations

import asyncio
import json
import hashlib
import os
from pathlib import Path
from time import perf_counter
from typing import Any, Callable
from uuid import UUID
from datetime import datetime, timezone, timedelta

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
import sqlalchemy as sa
from sqlalchemy.orm import Session

from packages.auth import AuthError, AuthRuntimeConfig, AuthService
from packages.evaluation.service import OnlineEvaluationService
from packages.llm.embeddings.base import EmbeddingProvider
from packages.llm.embeddings.factory import create_embedding_provider_from_env
from packages.llm.text_generation.factory import create_text_generation_provider
from packages.memory.long_term.ingestion.ingestion_service import MemoryIngestionService
from packages.memory.long_term.lifecycle.rebuild import MemoryRebuildService
from packages.memory.long_term.runtime_config import MemoryRuntimeConfig
from packages.memory.long_term.search.search_service import MemorySearchService
from packages.memory.project_memory.project_memory_service import ProjectMemoryService
from packages.memory.working_memory.context_builder import ContextBuilder
from packages.memory.working_memory.hybrid_compressor import HybridContextCompressor
from packages.retrieval.chunking.simple_text_chunker import SimpleTextChunker
from packages.storage.postgres.repositories.agent_run_repository import AgentRunRepository
from packages.storage.postgres.repositories.character_repository import CharacterRepository
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
from packages.storage.postgres.repositories.foreshadowing_repository import ForeshadowingRepository
from packages.storage.postgres.repositories.outline_repository import OutlineRepository
from packages.storage.postgres.repositories.project_repository import ProjectRepository
from packages.storage.postgres.repositories.project_membership_repository import (
    ProjectMembershipRepository,
)
from packages.storage.postgres.repositories.project_transfer_job_repository import (
    ProjectTransferJobRepository,
)
from packages.storage.postgres.repositories.session_repository import SessionRepository
from packages.storage.postgres.repositories.skill_run_repository import SkillRunRepository
from packages.storage.postgres.repositories.timeline_event_repository import TimelineEventRepository
from packages.storage.postgres.repositories.tool_call_repository import ToolCallRepository
from packages.storage.postgres.repositories.user_repository import UserRepository
from packages.storage.postgres.repositories.workflow_run_repository import WorkflowRunRepository
from packages.storage.postgres.repositories.auth_refresh_token_repository import (
    AuthRefreshTokenRepository,
)
from packages.storage.postgres.repositories.audit_event_repository import (
    AuditEventRepository,
)
from packages.storage.postgres.repositories.backup_run_repository import (
    BackupRunRepository,
)
from packages.storage.postgres.repositories.webhook_delivery_repository import (
    WebhookDeliveryRepository,
)
from packages.storage.postgres.repositories.webhook_subscription_repository import (
    WebhookSubscriptionRepository,
)
from packages.storage.postgres.repositories.world_entry_repository import WorldEntryRepository
from packages.storage.postgres.session import create_session_factory
from packages.observability import InMemoryMetrics, render_prometheus
from packages.schemas import SchemaRegistry, SchemaValidationError
from packages.sessions import SessionService
from packages.system import AuditService, BackupService
from packages.transfer import ProjectTransferService
from packages.webhooks import WebhookService
from packages.workflows.chapter_generation.context_provider import (
    SQLAlchemyStoryContextProvider,
)
from packages.workflows.chapter_generation.service import (
    ChapterGenerationWorkflowError,
    ChapterGenerationWorkflowService,
)
from packages.workflows.chapter_generation.types import ChapterGenerationRequest
from packages.workflows.orchestration.runtime_config import OrchestratorRuntimeConfig
from packages.workflows.orchestration.service import WritingOrchestratorService
from packages.workflows.orchestration.run_events import (
    build_run_events,
    events_since_cursor,
    last_seq,
    terminal_status_reached,
)
from packages.workflows.orchestration.types import WorkflowRunRequest


class ChapterGeneratePayload(BaseModel):
    writing_goal: str = Field(..., min_length=1, description="写作目标，建议包含剧情推进目标、冲突点或本章任务。")
    chapter_no: int | None = Field(default=None, ge=1, description="目标章节号。为空时由 workflow 自行决定写入章节序号。")
    target_words: int = Field(default=1200, ge=200, le=5000, description="目标字数范围中心值。")
    style_hint: str | None = Field(default=None, description="风格提示，如“冷峻纪实”“高张力对话”。")
    include_memory_top_k: int = Field(default=8, ge=1, le=50, description="记忆检索候选条数上限。")
    context_token_budget: int | None = Field(
        default=None,
        ge=400,
        le=12000,
        description="上下文预算（近似 token）。为空则使用系统默认预算。",
    )
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="生成随机性。")
    chat_turns: list[dict] | None = Field(default=None, description="会话历史片段（短期记忆输入）。")
    working_notes: list[str] | None = Field(default=None, description="工作笔记/编辑指令。")


class ChapterGenerateResponse(BaseModel):
    trace_id: str = Field(..., description="链路追踪 ID。")
    agent_run_id: str = Field(..., description="章节生成 agent_run ID。")
    mock_mode: bool = Field(..., description="是否使用了 mock 文本生成。")
    chapter: dict = Field(..., description="章节产物（id/chapter_no/title/content/version 等）。")
    memory_ingestion: dict = Field(..., description="记忆摄入统计。")
    writer_structured: dict | None = Field(default=None, description="WriterOutputV2 结构化输出。")
    warnings: list[str] | None = Field(default=None, description="运行时警告。")
    skill_runs: list[dict] | None = Field(default=None, description="技能执行摘要。")


class WorkflowRunCreatePayload(BaseModel):
    workflow_type: str = Field(
        default="writing_full",
        min_length=1,
        description="工作流类型。常用：writing_full/outline_generation/chapter_generation/consistency_review/revision。",
    )
    writing_goal: str = Field(..., min_length=1, description="本次 run 的写作目标。")
    chapter_no: int | None = Field(default=None, ge=1, description="目标章节号。")
    target_words: int = Field(default=1200, ge=200, le=5000, description="目标字数。")
    style_hint: str | None = Field(default=None, description="文风提示。")
    include_memory_top_k: int = Field(default=8, ge=1, le=50, description="检索候选数量。")
    context_token_budget: int | None = Field(
        default=None,
        ge=400,
        le=12000,
        description="上下文预算（近似 token）。为空使用默认值。",
    )
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="生成温度。")
    chat_turns: list[dict] | None = Field(default=None, description="会话历史。")
    working_notes: list[str] | None = Field(default=None, description="工作笔记。")
    session_id: UUID | None = Field(default=None, description="关联会话 ID（可选）。")
    idempotency_key: str | None = Field(
        default=None,
        description="幂等键。重复提交同一键会复用已有 run。",
    )


class WorkflowRunCreateResponse(BaseModel):
    run_id: str = Field(..., description="workflow_run 主键。")
    status: str = Field(..., description="初始状态，通常为 queued。")
    trace_id: str = Field(..., description="链路追踪 ID。")
    request_id: str = Field(..., description="请求 ID。")


class RetrievalFeedbackPayload(BaseModel):
    project_id: UUID
    request_id: str = Field(..., min_length=1, description="检索请求 request_id。")
    user_id: str | None = Field(default=None, description="用户 UUID（可选）。")
    clicked_doc_id: str | None = Field(default=None, description="被点击的文档/chunk ID。")
    clicked: bool = Field(default=True, description="是否点击。")


class RetrievalFeedbackResponse(BaseModel):
    ok: bool = Field(..., description="反馈是否写入成功。")


class EvaluationFeedbackPayload(BaseModel):
    evaluation_type: str = Field(..., pattern="^(retrieval|writing)$", description="反馈类型：retrieval 或 writing。")
    request_id: str | None = Field(default=None, description="retrieval 类型必填。")
    workflow_run_id: UUID | None = Field(default=None, description="writing 类型必填。")
    user_id: str | None = Field(default=None, description="用户 UUID（可选）。")
    clicked_doc_id: str | None = Field(default=None, description="点击结果 ID（retrieval 场景）。")
    clicked: bool | None = Field(default=None, description="是否点击（retrieval 场景）。")
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    comment: str | None = Field(default=None, description="自由评论。")


class EvaluationFeedbackResponse(BaseModel):
    ok: bool = Field(..., description="反馈写入是否成功。")
    evaluation_type: str = Field(..., description="反馈类型。")
    detail: str | None = Field(default=None, description="失败时的说明信息。")


class UserPreferencesPayload(BaseModel):
    preferences: dict = Field(default_factory=dict, description="用户偏好 JSON，将用于检索约束与写作风格约束。")


class UserPreferencesResponse(BaseModel):
    ok: bool = Field(..., description="更新是否成功。")
    user_id: str = Field(..., description="被更新用户 ID。")
    rebuild_chunks: int = Field(..., description="偏好记忆重建生成的 chunk 数。")


class UserCreatePayload(BaseModel):
    username: str = Field(..., min_length=1, description="用户名（唯一）。")
    email: str | None = Field(default=None, description="邮箱（可选，唯一）。")
    password_hash: str | None = Field(default=None, description="密码哈希（可选）。")
    preferences: dict = Field(default_factory=dict, description="用户偏好 JSON。")


class UserUpdatePayload(BaseModel):
    username: str | None = Field(default=None, min_length=1, description="用户名。")
    email: str | None = Field(default=None, description="邮箱。")
    password_hash: str | None = Field(default=None, description="密码哈希。")
    preferences: dict | None = Field(default=None, description="用户偏好 JSON。")


class UserResponse(BaseModel):
    id: str
    username: str
    email: str | None
    preferences: dict
    created_at: str | None
    updated_at: str | None


class ProjectCreatePayload(BaseModel):
    title: str = Field(..., min_length=1, description="项目标题。")
    genre: str | None = Field(default=None, description="题材，如悬疑/奇幻。")
    premise: str | None = Field(default=None, description="故事前提。")
    owner_user_id: UUID | None = Field(default=None, description="项目 owner 用户 ID。")
    metadata_json: dict = Field(default_factory=dict, description="项目扩展元数据。")


class ProjectUpdatePayload(BaseModel):
    title: str | None = Field(default=None, min_length=1, description="项目标题。")
    genre: str | None = Field(default=None, description="题材。")
    premise: str | None = Field(default=None, description="故事前提。")
    owner_user_id: UUID | None = Field(default=None, description="项目 owner 用户 ID。")
    metadata_json: dict | None = Field(default=None, description="项目扩展元数据。")


class ProjectResponse(BaseModel):
    id: str
    owner_user_id: str | None
    title: str
    genre: str | None
    premise: str | None
    metadata_json: dict
    created_at: str | None
    updated_at: str | None


class OutlineSeedPayload(BaseModel):
    title: str | None = Field(default=None, description="初始化大纲标题。")
    content: str | None = Field(default=None, description="初始化大纲正文。")
    structure_json: dict = Field(default_factory=dict, description="结构化大纲 JSON。")
    set_active: bool = Field(default=True, description="是否设为 active 版本。")


class CharacterCreatePayload(BaseModel):
    name: str = Field(..., min_length=1, description="角色名。")
    role_type: str | None = Field(default=None, description="角色类型。")
    age: int | None = Field(default=None, ge=0, le=200, description="年龄。")
    faction: str | None = Field(default=None, description="阵营。")
    profile_json: dict = Field(default_factory=dict, description="角色设定 JSON。")
    speech_style_json: dict = Field(default_factory=dict, description="说话风格 JSON。")
    arc_status_json: dict = Field(default_factory=dict, description="角色弧状态 JSON。")
    is_canonical: bool = Field(default=True, description="是否正史角色。")


class CharacterUpdatePayload(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    role_type: str | None = None
    age: int | None = Field(default=None, ge=0, le=200)
    faction: str | None = None
    profile_json: dict | None = None
    speech_style_json: dict | None = None
    arc_status_json: dict | None = None
    is_canonical: bool | None = None
    version: int | None = Field(default=None, ge=1)


class CharacterResponse(BaseModel):
    id: str
    project_id: str
    name: str
    role_type: str | None
    age: int | None
    faction: str | None
    profile_json: dict
    speech_style_json: dict
    arc_status_json: dict
    version: int
    is_canonical: bool
    created_at: str | None
    updated_at: str | None


class WorldEntryCreatePayload(BaseModel):
    entry_type: str | None = Field(default=None, description="条目类型，如地点/组织/规则。")
    title: str | None = Field(default=None, description="条目标题。")
    content: str | None = Field(default=None, description="条目正文。")
    metadata_json: dict = Field(default_factory=dict, description="扩展元数据。")
    is_canonical: bool = Field(default=True, description="是否正史设定。")


class WorldEntryUpdatePayload(BaseModel):
    entry_type: str | None = None
    title: str | None = None
    content: str | None = None
    metadata_json: dict | None = None
    is_canonical: bool | None = None
    version: int | None = Field(default=None, ge=1)


class WorldEntryResponse(BaseModel):
    id: str
    project_id: str
    entry_type: str | None
    title: str | None
    content: str | None
    metadata_json: dict
    version: int
    is_canonical: bool
    created_at: str | None
    updated_at: str | None


class TimelineEventCreatePayload(BaseModel):
    chapter_no: int | None = Field(default=None, ge=1, description="关联章节号。")
    event_title: str | None = Field(default=None, description="事件标题。")
    event_desc: str | None = Field(default=None, description="事件描述。")
    location: str | None = Field(default=None, description="事件地点。")
    involved_characters: list[str] = Field(default_factory=list, description="涉及角色名列表。")
    causal_links: list[dict] = Field(default_factory=list, description="因果链路 JSON 列表。")


class TimelineEventUpdatePayload(BaseModel):
    chapter_no: int | None = Field(default=None, ge=1)
    event_title: str | None = None
    event_desc: str | None = None
    location: str | None = None
    involved_characters: list[str] | None = None
    causal_links: list[dict] | None = None


class TimelineEventResponse(BaseModel):
    id: str
    project_id: str
    chapter_no: int | None
    event_title: str | None
    event_desc: str | None
    location: str | None
    involved_characters: list[str]
    causal_links: list[dict]
    created_at: str | None
    updated_at: str | None


class ForeshadowingCreatePayload(BaseModel):
    setup_chapter_no: int | None = Field(default=None, ge=1)
    setup_text: str | None = None
    expected_payoff: str | None = None
    payoff_chapter_no: int | None = Field(default=None, ge=1)
    payoff_text: str | None = None
    status: str = Field(default="open", pattern="^(open|resolved)$")


class ForeshadowingUpdatePayload(BaseModel):
    setup_chapter_no: int | None = Field(default=None, ge=1)
    setup_text: str | None = None
    expected_payoff: str | None = None
    payoff_chapter_no: int | None = Field(default=None, ge=1)
    payoff_text: str | None = None
    status: str | None = Field(default=None, pattern="^(open|resolved)$")


class ForeshadowingResponse(BaseModel):
    id: str
    project_id: str
    setup_chapter_no: int | None
    setup_text: str | None
    expected_payoff: str | None
    payoff_chapter_no: int | None
    payoff_text: str | None
    status: str
    created_at: str | None
    updated_at: str | None


class ProjectBootstrapPayload(BaseModel):
    outline: OutlineSeedPayload | None = Field(default=None, description="初始化大纲，可选。")
    characters: list[CharacterCreatePayload] = Field(default_factory=list, description="初始化角色列表。")
    world_entries: list[WorldEntryCreatePayload] = Field(default_factory=list, description="初始化世界观条目。")
    timeline_events: list[TimelineEventCreatePayload] = Field(default_factory=list, description="初始化时间线事件。")
    foreshadowings: list[ForeshadowingCreatePayload] = Field(default_factory=list, description="初始化伏笔列表。")


class ProjectBootstrapResponse(BaseModel):
    ok: bool
    project_id: str
    outline_id: str | None
    created_counts: dict


class ChapterPublishResponse(BaseModel):
    ok: bool
    chapter_id: str
    status: str


class ChapterCreatePayload(BaseModel):
    title: str | None = Field(default=None, description="章节标题。")
    content: str | None = Field(default=None, description="章节正文。")
    summary: str | None = Field(default=None, description="章节摘要。")


class ChapterUpdatePayload(BaseModel):
    title: str | None = Field(default=None, description="章节标题。")
    content: str | None = Field(default=None, description="章节正文。")
    summary: str | None = Field(default=None, description="章节摘要。")
    status: str | None = Field(default=None, pattern="^(draft|published)$", description="章节状态。")


class AuthRegisterPayload(BaseModel):
    username: str = Field(..., min_length=1)
    email: str | None = Field(default=None)
    password: str = Field(..., min_length=6)
    preferences: dict = Field(default_factory=dict)


class AuthLoginPayload(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class AuthRefreshPayload(BaseModel):
    refresh_token: str = Field(..., min_length=10)


class AuthLogoutPayload(BaseModel):
    refresh_token: str | None = Field(default=None)


class AuthTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    refresh_expires_at: str
    user: dict


class ProjectMemberUpsertPayload(BaseModel):
    user_id: UUID
    role: str = Field(..., pattern="^(owner|editor|viewer)$")
    status: str = Field(default="active", pattern="^(active|invited|disabled)$")
    note: str | None = Field(default=None)


class SessionCreatePayload(BaseModel):
    title: str | None = Field(default=None)
    metadata_json: dict = Field(default_factory=dict)


class SessionMessageCreatePayload(BaseModel):
    role: str = Field(default="user", pattern="^(system|user|assistant|tool)$")
    content: str = Field(..., min_length=1)
    token_count: int | None = Field(default=None, ge=0)
    metadata_json: dict = Field(default_factory=dict)


class SessionSummarizePayload(BaseModel):
    max_items: int = Field(default=20, ge=1, le=200)


class ChapterCandidateRejectPayload(BaseModel):
    cancel_run: bool = Field(default=True, description="拒绝后是否取消 run。false 表示保持 waiting_review。")


class WebhookSubscriptionCreatePayload(BaseModel):
    event_type: str = Field(..., min_length=1)
    target_url: str = Field(..., min_length=8)
    secret: str = Field(..., min_length=8)
    max_retries: int = Field(default=8, ge=1, le=16)
    timeout_seconds: int = Field(default=10, ge=1, le=120)
    headers_json: dict = Field(default_factory=dict)
    metadata_json: dict = Field(default_factory=dict)


class WebhookSubscriptionUpdatePayload(BaseModel):
    status: str | None = Field(default=None, pattern="^(active|paused)$")
    max_retries: int | None = Field(default=None, ge=1, le=16)
    timeout_seconds: int | None = Field(default=None, ge=1, le=120)
    headers_json: dict | None = None
    metadata_json: dict | None = None


class ProjectExportPayload(BaseModel):
    include_chapters: bool = True
    include_versions: bool = True
    include_long_term_memory: bool = False
    output_dir: str = Field(default="data/exports")


class ProjectImportPayload(BaseModel):
    source_path: str = Field(..., min_length=3)


def _build_embedding_provider() -> EmbeddingProvider:
    return create_embedding_provider_from_env()


def _build_workflow_service(db: Session) -> ChapterGenerationWorkflowService:
    embedding_provider = _build_embedding_provider()
    memory_cfg = MemoryRuntimeConfig.from_env()
    chunk_size = max(64, int(memory_cfg.ingestion.chunk_size))
    chunk_overlap = max(0, min(int(memory_cfg.ingestion.chunk_overlap), chunk_size - 1))
    text_provider = create_text_generation_provider()
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
                enable_llm=memory_cfg.context_compression.enable_llm,
                llm_trigger_ratio=memory_cfg.context_compression.llm_trigger_ratio,
                llm_min_gain_ratio=memory_cfg.context_compression.llm_min_gain_ratio,
                llm_max_input_chars=memory_cfg.context_compression.llm_max_input_chars,
            ),
            llm_max_items=memory_cfg.context_compression.llm_max_items,
            min_relevance_score=memory_cfg.context_compression.context_min_relevance_score,
            relative_score_floor=memory_cfg.context_compression.context_relative_score_floor,
            min_keep_rows=memory_cfg.context_compression.context_min_keep_rows,
            max_rows=memory_cfg.context_compression.context_max_rows,
        ),
    )

    return ChapterGenerationWorkflowService(
        project_repo=ProjectRepository(db),
        chapter_repo=ChapterRepository(db),
        agent_run_repo=AgentRunRepository(db),
        tool_call_repo=ToolCallRepository(db),
        skill_run_repo=SkillRunRepository(db),
        story_context_provider=SQLAlchemyStoryContextProvider(db),
        project_memory_service=project_memory_service,
        ingestion_service=ingestion_service,
        text_provider=text_provider,
        default_context_token_budget=memory_cfg.context_compression.context_token_budget_default,
    )


def _build_search_service(db: Session) -> MemorySearchService:
    return MemorySearchService(
        embedding_provider=_build_embedding_provider(),
        memory_repo=MemoryChunkRepository(db),
    )


def _rebuild_user_preferences_memory(*, db: Session, project_id, user_id, preferences: dict) -> int:
    embedding_provider = _build_embedding_provider()
    memory_cfg = MemoryRuntimeConfig.from_env()
    chunk_size = max(64, int(memory_cfg.ingestion.chunk_size))
    chunk_overlap = max(0, min(int(memory_cfg.ingestion.chunk_overlap), chunk_size - 1))
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
    rebuild_service = MemoryRebuildService(
        ingestion_service=ingestion_service,
        memory_repo=memory_repo,
    )
    return int(
        rebuild_service.rebuild_source(
            project_id=project_id,
            source_type="user_preference",
            source_id=user_id,
            text=json.dumps(dict(preferences or {}), ensure_ascii=False),
            chunk_type="user_preference",
            metadata_json={"kind": "user_preferences"},
        )
    )


def _build_orchestrator_service(db: Session) -> WritingOrchestratorService:
    return WritingOrchestratorService.build_default(db)


def _build_evaluation_service(db: Session) -> OnlineEvaluationService:
    cfg = OrchestratorRuntimeConfig.from_env()
    root = Path.cwd()
    schema_root = Path(cfg.schema_root)
    if not schema_root.is_absolute():
        schema_root = (root / schema_root).resolve()
    schema_registry = SchemaRegistry(schema_root)
    return OnlineEvaluationService(
        repo=EvaluationRepository(db),
        schema_registry=schema_registry,
        schema_strict=cfg.schema_strict,
        schema_degrade_mode=cfg.schema_degrade_mode,
    )


def _build_auth_service(db: Session) -> AuthService:
    cfg = AuthRuntimeConfig.from_env()
    env_name = os.environ.get("WRITER_ENV", "").strip().lower()
    if cfg.enforce_prod_secret and env_name in {"prod", "production"}:
        if cfg.jwt_secret == "dev-insecure-jwt-secret-change-me":
            raise RuntimeError("生产环境必须配置 WRITER_AUTH_JWT_SECRET")
    return AuthService(
        user_repo=UserRepository(db),
        refresh_repo=AuthRefreshTokenRepository(db),
        config=cfg,
    )


def _extract_bearer_token(req: Request) -> str:
    auth = req.headers.get("Authorization", "").strip()
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="缺少 Bearer token")
    token = auth[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="token 为空")
    return token


def _extract_ws_bearer_token(ws: WebSocket) -> str:
    query_token = str(ws.query_params.get("access_token") or ws.query_params.get("token") or "").strip()
    if query_token:
        return query_token
    auth = str(ws.headers.get("Authorization") or ws.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return token
    raise AuthError("缺少 Bearer token")


def _serialize_metrics_snapshot(counters: dict, histograms: dict) -> dict[str, Any]:
    out_counters: list[dict[str, Any]] = []
    for (name, labels), value in sorted(counters.items(), key=lambda x: (x[0][0], x[0][1])):
        out_counters.append(
            {
                "name": str(name),
                "labels": {str(k): str(v) for k, v in list(labels or [])},
                "value": float(value or 0.0),
            }
        )

    out_histograms: list[dict[str, Any]] = []
    for (name, labels), values in sorted(histograms.items(), key=lambda x: (x[0][0], x[0][1])):
        normalized = [float(v) for v in list(values or [])]
        count = len(normalized)
        total = float(sum(normalized)) if normalized else 0.0
        p95 = float(_percentile(normalized, 0.95)) if normalized else 0.0
        out_histograms.append(
            {
                "name": str(name),
                "labels": {str(k): str(v) for k, v in list(labels or [])},
                "count": count,
                "sum": total,
                "p95": p95,
            }
        )
    return {"counters": out_counters, "histograms": out_histograms}


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    idx = int(max(0, min(len(ordered) - 1, round((len(ordered) - 1) * float(q)))))
    return float(ordered[idx])


def _hash_ip(req: Request) -> str | None:
    host = req.client.host if req.client is not None else None
    if not host:
        return None
    return hashlib.sha256(host.encode("utf-8")).hexdigest()


def _is_system_admin(user: dict[str, Any]) -> bool:
    prefs = dict(user.get("preferences") or {})
    return bool(prefs.get("is_admin"))


def _serialize_user(row) -> dict:
    return {
        "id": str(row.id),
        "username": row.username,
        "email": row.email,
        "preferences": dict(row.preferences or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_project(row) -> dict:
    return {
        "id": str(row.id),
        "owner_user_id": str(row.owner_user_id) if row.owner_user_id is not None else None,
        "title": row.title,
        "genre": row.genre,
        "premise": row.premise,
        "metadata_json": dict(row.metadata_json or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_character(row) -> dict:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "name": row.name,
        "role_type": row.role_type,
        "age": row.age,
        "faction": row.faction,
        "profile_json": dict(row.profile_json or {}),
        "speech_style_json": dict(row.speech_style_json or {}),
        "arc_status_json": dict(row.arc_status_json or {}),
        "version": int(row.version or 1),
        "is_canonical": bool(row.is_canonical),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_world_entry(row) -> dict:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "entry_type": row.entry_type,
        "title": row.title,
        "content": row.content,
        "metadata_json": dict(row.metadata_json or {}),
        "version": int(row.version or 1),
        "is_canonical": bool(row.is_canonical),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_timeline_event(row) -> dict:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "chapter_no": row.chapter_no,
        "event_title": row.event_title,
        "event_desc": row.event_desc,
        "location": row.location,
        "involved_characters": list(row.involved_characters or []),
        "causal_links": list(row.causal_links or []),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_foreshadowing(row) -> dict:
    status = row.status.value if hasattr(row.status, "value") else row.status
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "setup_chapter_no": row.setup_chapter_no,
        "setup_text": row.setup_text,
        "expected_payoff": row.expected_payoff,
        "payoff_chapter_no": row.payoff_chapter_no,
        "payoff_text": row.payoff_text,
        "status": str(status),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_chapter(row) -> dict:
    status = row.status.value if hasattr(row.status, "value") else row.status
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "chapter_no": int(row.chapter_no),
        "title": row.title,
        "content": row.content,
        "summary": row.summary,
        "status": str(status),
        "draft_version": int(row.draft_version or 1),
        "created_by": str(row.created_by) if row.created_by is not None else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_chapter_version(row) -> dict:
    return {
        "id": int(row.id),
        "chapter_id": str(row.chapter_id),
        "version_no": int(row.version_no),
        "content": row.content,
        "summary": row.summary,
        "source_agent": row.source_agent,
        "source_workflow": row.source_workflow,
        "trace_id": row.trace_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_project_membership(row) -> dict:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "user_id": str(row.user_id),
        "role": str(row.role),
        "status": str(row.status),
        "invited_by": str(row.invited_by) if row.invited_by is not None else None,
        "note": row.note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_session(row) -> dict:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "user_id": str(row.user_id) if row.user_id is not None else None,
        "linked_workflow_run_id": (
            str(row.linked_workflow_run_id) if row.linked_workflow_run_id is not None else None
        ),
        "title": row.title,
        "summary": row.summary,
        "status": str(row.status),
        "metadata_json": dict(row.metadata_json or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_session_message(row) -> dict:
    return {
        "id": int(row.id),
        "session_id": str(row.session_id),
        "project_id": str(row.project_id),
        "user_id": str(row.user_id) if row.user_id is not None else None,
        "role": str(row.role),
        "content": row.content,
        "token_count": row.token_count,
        "metadata_json": dict(row.metadata_json or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _serialize_chapter_candidate(row) -> dict:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "workflow_run_id": str(row.workflow_run_id) if row.workflow_run_id is not None else None,
        "workflow_step_id": int(row.workflow_step_id) if row.workflow_step_id is not None else None,
        "agent_run_id": str(row.agent_run_id) if row.agent_run_id is not None else None,
        "chapter_no": int(row.chapter_no),
        "title": row.title,
        "summary": row.summary,
        "content": row.content,
        "status": str(row.status),
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "approved_by": str(row.approved_by) if row.approved_by is not None else None,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "rejected_by": str(row.rejected_by) if row.rejected_by is not None else None,
        "rejected_at": row.rejected_at.isoformat() if row.rejected_at else None,
        "approved_chapter_id": (
            str(row.approved_chapter_id) if row.approved_chapter_id is not None else None
        ),
        "approved_version_id": (
            int(row.approved_version_id) if row.approved_version_id is not None else None
        ),
        "memory_chunks_count": int(row.memory_chunks_count or 0),
        "trace_id": row.trace_id,
        "request_id": row.request_id,
        "metadata_json": dict(row.metadata_json or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_webhook_subscription(row) -> dict:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "created_by": str(row.created_by) if row.created_by is not None else None,
        "event_type": row.event_type,
        "target_url": row.target_url,
        "status": str(row.status),
        "max_retries": int(row.max_retries or 8),
        "timeout_seconds": int(row.timeout_seconds or 10),
        "headers_json": dict(row.headers_json or {}),
        "metadata_json": dict(row.metadata_json or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_webhook_delivery(row) -> dict:
    return {
        "id": str(row.id),
        "event_id": row.event_id,
        "subscription_id": str(row.subscription_id),
        "project_id": str(row.project_id),
        "event_type": row.event_type,
        "status": str(row.status),
        "attempt_count": int(row.attempt_count or 0),
        "max_attempts": int(row.max_attempts or 8),
        "next_attempt_at": row.next_attempt_at.isoformat() if row.next_attempt_at else None,
        "response_status": row.response_status,
        "response_body": row.response_body,
        "error_message": row.error_message,
        "trace_id": row.trace_id,
        "request_id": row.request_id,
        "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_backup_run(row) -> dict:
    return {
        "id": str(row.id),
        "backup_type": str(row.backup_type),
        "status": str(row.status),
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "size_bytes": int(row.size_bytes) if row.size_bytes is not None else None,
        "checksum": row.checksum,
        "file_path": row.file_path,
        "error_message": row.error_message,
        "metadata_json": dict(row.metadata_json or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_transfer_job(row) -> dict:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id) if row.project_id is not None else None,
        "created_by": str(row.created_by) if row.created_by is not None else None,
        "job_type": str(row.job_type),
        "status": str(row.status),
        "source_path": row.source_path,
        "target_path": row.target_path,
        "include_chapters": bool(row.include_chapters),
        "include_versions": bool(row.include_versions),
        "include_long_term_memory": bool(row.include_long_term_memory),
        "size_bytes": int(row.size_bytes) if row.size_bytes is not None else None,
        "checksum": row.checksum,
        "error_message": row.error_message,
        "manifest_json": dict(row.manifest_json or {}),
        "metadata_json": dict(row.metadata_json or {}),
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def create_app(
    workflow_factory: Callable[[Session], ChapterGenerationWorkflowService] | None = None,
    orchestrator_factory: Callable[[Session], WritingOrchestratorService] | None = None,
    search_factory: Callable[[Session], MemorySearchService] | None = None,
    evaluation_factory: Callable[[Session], OnlineEvaluationService] | None = None,
) -> FastAPI:
    app = FastAPI(
        title="WriterAgent API",
        version="2.0.0",
        description=(
            "WriterAgent 写作后端 API。"
            "提供写作工作流编排、章节生成、检索反馈、在线评测与用户偏好接入能力。"
            "默认主入口为 v2 异步编排接口。"
        ),
        openapi_tags=[
            {"name": "System", "description": "系统健康检查。"},
            {"name": "V1 Compatibility", "description": "兼容模式接口（默认关闭）。"},
            {"name": "Users", "description": "用户创建与偏好管理。"},
            {"name": "Projects", "description": "项目创建与查询。"},
            {"name": "Bootstrap", "description": "项目初始化批量导入入口。"},
            {"name": "Story Assets", "description": "角色/世界观/时间线/伏笔管理。"},
            {"name": "Chapters", "description": "章节与版本管理。"},
            {"name": "Writing Runs", "description": "创建/查询/取消写作 run。"},
            {"name": "Workflows", "description": "按单工作流类型触发运行。"},
            {"name": "Outlines", "description": "大纲查询。"},
            {"name": "Consistency", "description": "一致性报告查询。"},
            {"name": "Retrieval", "description": "检索反馈回流。"},
            {"name": "Evaluation", "description": "在线评测反馈与统计查询。"},
        ],
    )
    orchestrator_cfg = OrchestratorRuntimeConfig.from_env()
    session_factory = None
    app.state.session_factory = None
    app.state.orchestrator_cfg = orchestrator_cfg
    app.state.workflow_factory = workflow_factory or _build_workflow_service
    app.state.orchestrator_factory = orchestrator_factory or _build_orchestrator_service
    app.state.search_factory = search_factory or _build_search_service
    app.state.evaluation_factory = evaluation_factory or _build_evaluation_service
    app.state.metrics_registry = InMemoryMetrics()

    @app.middleware("http")
    async def _metrics_middleware(request: Request, call_next):
        started = perf_counter()
        method = request.method.upper()
        path = request.url.path
        status_code = 500
        try:
            response = await call_next(request)
            status_code = int(response.status_code)
            return response
        finally:
            latency_ms = (perf_counter() - started) * 1000.0
            app.state.metrics_registry.inc(
                "writeragent_api_requests_total",
                1,
                method=method,
                path=path,
                status=str(status_code),
            )
            app.state.metrics_registry.observe(
                "writeragent_api_latency_ms",
                latency_ms,
                method=method,
                path=path,
                status=str(status_code),
            )

    @app.middleware("http")
    async def _auth_rbac_middleware(request: Request, call_next):
        path = request.url.path
        if not path.startswith("/v2"):
            return await call_next(request)

        allow_anonymous_prefixes = (
            "/v2/auth/register",
            "/v2/auth/login",
            "/v2/auth/refresh",
        )
        if any(path.startswith(prefix) for prefix in allow_anonymous_prefixes):
            return await call_next(request)

        nonlocal session_factory
        if session_factory is None:
            session_factory = create_session_factory()
            app.state.session_factory = session_factory

        db = session_factory()
        try:
            try:
                user = current_user(request, db)
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
            request.state.current_user = user

            segments = [seg for seg in path.split("/") if seg]
            project_id = None
            if len(segments) >= 3 and segments[0] == "v2" and segments[1] == "projects":
                try:
                    project_id = UUID(segments[2])
                except ValueError:
                    project_id = None

            if project_id is not None:
                min_role = "viewer" if request.method.upper() in {"GET", "HEAD"} else "editor"
                if len(segments) == 3 and request.method.upper() in {"PATCH", "DELETE"}:
                    min_role = "owner"
                if len(segments) >= 4 and segments[3] in {"members", "webhooks"} and request.method.upper() != "GET":
                    min_role = "owner"
                try:
                    ensure_project_role(db=db, project_id=project_id, user=user, min_role=min_role)
                except HTTPException as exc:
                    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        finally:
            db.close()

        return await call_next(request)

    def get_db():
        nonlocal session_factory
        if session_factory is None:
            session_factory = create_session_factory()
            app.state.session_factory = session_factory
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    def ensure_project_exists(db: Session, project_id: UUID):
        row = ProjectRepository(db).get(project_id)
        if row is None:
            raise HTTPException(status_code=404, detail="project 不存在")
        return row

    def current_user(req: Request, db: Session) -> dict[str, Any]:
        token = _extract_bearer_token(req)
        auth = _build_auth_service(db)
        try:
            return auth.authenticate_access_token(token)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    def ensure_project_role(
        *,
        db: Session,
        project_id: UUID,
        user: dict[str, Any],
        min_role: str = "viewer",
    ) -> None:
        user_id = UUID(str(user["id"]))
        membership_repo = ProjectMembershipRepository(db)
        if membership_repo.has_role(project_id=project_id, user_id=user_id, min_role=min_role):
            return
        raise HTTPException(status_code=403, detail=f"需要项目角色 {min_role}")

    @app.get(
        "/healthz",
        tags=["System"],
        summary="健康检查",
        description="服务存活探针，供网关与部署系统检测应用是否可用。",
    )
    def healthz() -> dict:
        return {"status": "ok"}

    @app.post(
        "/v2/auth/register",
        response_model=AuthTokenResponse,
        tags=["Users"],
        summary="注册并获取 token",
        description="创建账号后立即返回 access/refresh token。",
    )
    def auth_register(payload: AuthRegisterPayload, req: Request, db: Session = Depends(get_db)) -> AuthTokenResponse:
        auth = _build_auth_service(db)
        try:
            data = auth.register(
                username=payload.username,
                email=payload.email,
                password=payload.password,
                preferences=dict(payload.preferences or {}),
            )
        except AuthError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return AuthTokenResponse(**data)

    @app.post(
        "/v2/auth/login",
        response_model=AuthTokenResponse,
        tags=["Users"],
        summary="登录并获取 token",
        description="使用 username/password 登录。",
    )
    def auth_login(payload: AuthLoginPayload, req: Request, db: Session = Depends(get_db)) -> AuthTokenResponse:
        auth = _build_auth_service(db)
        try:
            data = auth.login(
                username=payload.username,
                password=payload.password,
                ip_hash=_hash_ip(req),
                user_agent=req.headers.get("User-Agent"),
            )
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return AuthTokenResponse(**data)

    @app.post(
        "/v2/auth/refresh",
        response_model=AuthTokenResponse,
        tags=["Users"],
        summary="刷新 token",
        description="通过 refresh_token 轮换并获取新 token 对。",
    )
    def auth_refresh(payload: AuthRefreshPayload, req: Request, db: Session = Depends(get_db)) -> AuthTokenResponse:
        auth = _build_auth_service(db)
        try:
            data = auth.refresh(
                refresh_token=payload.refresh_token,
                ip_hash=_hash_ip(req),
                user_agent=req.headers.get("User-Agent"),
            )
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return AuthTokenResponse(**data)

    @app.post(
        "/v2/auth/logout",
        tags=["Users"],
        summary="注销",
        description="撤销 refresh_token（若提供）。",
    )
    def auth_logout(payload: AuthLogoutPayload, db: Session = Depends(get_db)) -> dict:
        auth = _build_auth_service(db)
        auth.logout(refresh_token=payload.refresh_token)
        return {"ok": True}

    @app.get(
        "/v2/auth/me",
        tags=["Users"],
        summary="当前用户信息",
        description="根据 access token 返回当前用户。",
    )
    def auth_me(req: Request, db: Session = Depends(get_db)) -> dict:
        user = current_user(req, db)
        return {"user": user}

    @app.post(
        "/v2/users",
        response_model=UserResponse,
        tags=["Users"],
        summary="创建用户",
        description="创建写作系统用户，支持初始偏好配置。",
    )
    def create_user(payload: UserCreatePayload, db: Session = Depends(get_db)) -> UserResponse:
        repo = UserRepository(db)
        if repo.get_by_username(payload.username) is not None:
            raise HTTPException(status_code=409, detail="username 已存在")
        row = repo.create(
            username=payload.username,
            email=payload.email,
            password_hash=payload.password_hash,
            preferences=dict(payload.preferences or {}),
        )
        return UserResponse(**_serialize_user(row))

    @app.get(
        "/v2/users",
        tags=["Users"],
        summary="查询用户列表",
        description="返回用户列表（管理用途）。",
    )
    def list_users(limit: int = 100, db: Session = Depends(get_db)) -> dict:
        rows = UserRepository(db).list_all(limit=max(1, min(limit, 500)))
        return {"items": [_serialize_user(row) for row in rows]}

    @app.get(
        "/v2/users/{user_id}",
        response_model=UserResponse,
        tags=["Users"],
        summary="查询用户详情",
        description="按 user_id 查询用户。",
    )
    def get_user(user_id: UUID, db: Session = Depends(get_db)) -> UserResponse:
        row = UserRepository(db).get(user_id)
        if row is None:
            raise HTTPException(status_code=404, detail="user 不存在")
        return UserResponse(**_serialize_user(row))

    @app.patch(
        "/v2/users/{user_id}",
        response_model=UserResponse,
        tags=["Users"],
        summary="更新用户",
        description="更新用户基础信息或偏好。",
    )
    def update_user(user_id: UUID, payload: UserUpdatePayload, db: Session = Depends(get_db)) -> UserResponse:
        row = UserRepository(db).update(
            user_id,
            username=payload.username,
            email=payload.email,
            password_hash=payload.password_hash,
            preferences=payload.preferences,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="user 不存在")
        return UserResponse(**_serialize_user(row))

    @app.post(
        "/v2/projects",
        response_model=ProjectResponse,
        tags=["Projects"],
        summary="创建项目",
        description="创建长篇小说项目，返回 project_id 供后续工作流调用。",
    )
    def create_project(payload: ProjectCreatePayload, req: Request, db: Session = Depends(get_db)) -> ProjectResponse:
        user = current_user(req, db)
        if payload.owner_user_id is not None and UserRepository(db).get(payload.owner_user_id) is None:
            raise HTTPException(status_code=404, detail="owner_user_id 对应用户不存在")
        owner_user_id = payload.owner_user_id or UUID(str(user["id"]))
        row = ProjectRepository(db).create(
            title=payload.title,
            genre=payload.genre,
            premise=payload.premise,
            owner_user_id=owner_user_id,
        )
        if payload.metadata_json:
            row = ProjectRepository(db).update(
                row.id,
                metadata_json=dict(payload.metadata_json),
            )
        ProjectMembershipRepository(db).create_or_update(
            project_id=row.id,
            user_id=owner_user_id,
            role="owner",
            status="active",
        )
        return ProjectResponse(**_serialize_project(row))

    @app.get(
        "/v2/projects",
        tags=["Projects"],
        summary="查询项目列表",
        description="可按 owner_user_id 过滤。",
    )
    def list_projects(
        req: Request,
        owner_user_id: UUID | None = None,
        db: Session = Depends(get_db),
    ) -> dict:
        user = current_user(req, db)
        user_uuid = UUID(str(user["id"]))
        repo = ProjectRepository(db)
        if _is_system_admin(user):
            rows = repo.list_by_owner(owner_user_id) if owner_user_id is not None else repo.list_all()
        else:
            if owner_user_id is not None and str(owner_user_id) != str(user_uuid):
                raise HTTPException(status_code=403, detail="非管理员仅可查看自己的项目")
            membership_repo = ProjectMembershipRepository(db)
            memberships = membership_repo.list_by_user(user_id=user_uuid, include_disabled=False)
            if not memberships:
                owned = repo.list_by_owner(user_uuid)
                for item in owned:
                    membership_repo.create_or_update(
                        project_id=item.id,
                        user_id=user_uuid,
                        role="owner",
                        status="active",
                    )
                memberships = membership_repo.list_by_user(user_id=user_uuid, include_disabled=False)
            project_ids = [item.project_id for item in memberships]
            rows = [repo.get(pid) for pid in project_ids]
            rows = [row for row in rows if row is not None]
        return {"items": [_serialize_project(row) for row in rows]}

    @app.get(
        "/v2/projects/{project_id}",
        response_model=ProjectResponse,
        tags=["Projects"],
        summary="查询项目详情",
        description="按 project_id 查询项目基础信息。",
    )
    def get_project(project_id: UUID, db: Session = Depends(get_db)) -> ProjectResponse:
        row = ProjectRepository(db).get(project_id)
        if row is None:
            raise HTTPException(status_code=404, detail="project 不存在")
        return ProjectResponse(**_serialize_project(row))

    @app.patch(
        "/v2/projects/{project_id}",
        response_model=ProjectResponse,
        tags=["Projects"],
        summary="更新项目",
        description="更新项目标题、题材、前提和扩展元数据。",
    )
    def update_project(
        project_id: UUID,
        payload: ProjectUpdatePayload,
        db: Session = Depends(get_db),
    ) -> ProjectResponse:
        if payload.owner_user_id is not None and UserRepository(db).get(payload.owner_user_id) is None:
            raise HTTPException(status_code=404, detail="owner_user_id 对应用户不存在")
        row = ProjectRepository(db).update(
            project_id,
            title=payload.title,
            genre=payload.genre,
            premise=payload.premise,
            metadata_json=payload.metadata_json,
            owner_user_id=payload.owner_user_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="project 不存在")
        if payload.owner_user_id is not None:
            ProjectMembershipRepository(db).create_or_update(
                project_id=project_id,
                user_id=payload.owner_user_id,
                role="owner",
                status="active",
            )
        return ProjectResponse(**_serialize_project(row))

    @app.delete(
        "/v2/projects/{project_id}",
        tags=["Projects"],
        summary="删除项目",
        description="删除项目及其级联数据（谨慎操作）。",
    )
    def delete_project(project_id: UUID, req: Request, db: Session = Depends(get_db)) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ok = ProjectRepository(db).delete(project_id)
        if not ok:
            raise HTTPException(status_code=404, detail="project 不存在")
        AuditService(repo=AuditEventRepository(db)).log(
            action="project_delete",
            resource_type="project",
            resource_id=str(project_id),
            project_id=project_id,
            user_id=UUID(str(user["id"])),
        )
        return {"ok": True, "project_id": str(project_id)}

    @app.post(
        "/v2/projects/{project_id}/bootstrap",
        response_model=ProjectBootstrapResponse,
        tags=["Bootstrap"],
        summary="项目初始化导入",
        description=(
            "批量导入项目基础资产（大纲/角色/世界观/时间线/伏笔）。"
            "适用于新建长篇小说项目后的首轮初始化。"
        ),
    )
    def bootstrap_project(
        project_id: UUID,
        payload: ProjectBootstrapPayload,
        db: Session = Depends(get_db),
    ) -> ProjectBootstrapResponse:
        ensure_project_exists(db, project_id)
        outline_repo = OutlineRepository(db)
        character_repo = CharacterRepository(db)
        world_repo = WorldEntryRepository(db)
        timeline_repo = TimelineEventRepository(db)
        foreshadowing_repo = ForeshadowingRepository(db)

        outline_id: str | None = None
        created_counts = {
            "outline": 0,
            "characters": 0,
            "world_entries": 0,
            "timeline_events": 0,
            "foreshadowings": 0,
        }
        try:
            if payload.outline is not None:
                outline = outline_repo.create_version(
                    project_id=project_id,
                    title=payload.outline.title,
                    content=payload.outline.content,
                    structure_json=dict(payload.outline.structure_json or {}),
                    source_agent="user_seed",
                    source_workflow="project_bootstrap",
                    trace_id=None,
                    set_active=payload.outline.set_active,
                    auto_commit=False,
                )
                outline_id = str(outline.id)
                created_counts["outline"] = 1

            for item in payload.characters:
                character_repo.create(
                    project_id=project_id,
                    name=item.name,
                    role_type=item.role_type,
                    age=item.age,
                    faction=item.faction,
                    profile_json=item.profile_json,
                    speech_style_json=item.speech_style_json,
                    arc_status_json=item.arc_status_json,
                    is_canonical=item.is_canonical,
                    auto_commit=False,
                )
                created_counts["characters"] += 1

            for item in payload.world_entries:
                world_repo.create(
                    project_id=project_id,
                    entry_type=item.entry_type,
                    title=item.title,
                    content=item.content,
                    metadata_json=item.metadata_json,
                    is_canonical=item.is_canonical,
                    auto_commit=False,
                )
                created_counts["world_entries"] += 1

            for item in payload.timeline_events:
                timeline_repo.create(
                    project_id=project_id,
                    chapter_no=item.chapter_no,
                    event_title=item.event_title,
                    event_desc=item.event_desc,
                    location=item.location,
                    involved_characters=item.involved_characters,
                    causal_links=item.causal_links,
                    auto_commit=False,
                )
                created_counts["timeline_events"] += 1

            for item in payload.foreshadowings:
                foreshadowing_repo.create(
                    project_id=project_id,
                    setup_chapter_no=item.setup_chapter_no,
                    setup_text=item.setup_text,
                    expected_payoff=item.expected_payoff,
                    payoff_chapter_no=item.payoff_chapter_no,
                    payoff_text=item.payoff_text,
                    status=item.status,
                    auto_commit=False,
                )
                created_counts["foreshadowings"] += 1

            db.commit()
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"bootstrap 失败: {exc}") from exc

        return ProjectBootstrapResponse(
            ok=True,
            project_id=str(project_id),
            outline_id=outline_id,
            created_counts=created_counts,
        )

    @app.post(
        "/v2/projects/{project_id}/characters",
        response_model=CharacterResponse,
        tags=["Story Assets"],
        summary="新增角色",
        description="创建角色卡（可带 profile/speech/arc JSON）。",
    )
    def create_character(
        project_id: UUID,
        payload: CharacterCreatePayload,
        db: Session = Depends(get_db),
    ) -> CharacterResponse:
        ensure_project_exists(db, project_id)
        row = CharacterRepository(db).create(
            project_id=project_id,
            name=payload.name,
            role_type=payload.role_type,
            age=payload.age,
            faction=payload.faction,
            profile_json=payload.profile_json,
            speech_style_json=payload.speech_style_json,
            arc_status_json=payload.arc_status_json,
            is_canonical=payload.is_canonical,
        )
        return CharacterResponse(**_serialize_character(row))

    @app.get(
        "/v2/projects/{project_id}/characters",
        tags=["Story Assets"],
        summary="查询角色列表",
        description="按项目查询角色列表，可过滤 canonical_only。",
    )
    def list_characters(
        project_id: UUID,
        canonical_only: bool = False,
        limit: int = 200,
        db: Session = Depends(get_db),
    ) -> dict:
        ensure_project_exists(db, project_id)
        rows = CharacterRepository(db).list_by_project(
            project_id=project_id,
            canonical_only=canonical_only,
            limit=max(1, min(limit, 500)),
        )
        return {"items": [_serialize_character(row) for row in rows]}

    @app.get(
        "/v2/projects/{project_id}/characters/{character_id}",
        response_model=CharacterResponse,
        tags=["Story Assets"],
        summary="查询角色详情",
        description="按角色 ID 查询。",
    )
    def get_character(project_id: UUID, character_id: UUID, db: Session = Depends(get_db)) -> CharacterResponse:
        ensure_project_exists(db, project_id)
        row = CharacterRepository(db).get(character_id)
        if row is None or str(row.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="character 不存在")
        return CharacterResponse(**_serialize_character(row))

    @app.patch(
        "/v2/projects/{project_id}/characters/{character_id}",
        response_model=CharacterResponse,
        tags=["Story Assets"],
        summary="更新角色",
        description="局部更新角色信息。",
    )
    def update_character(
        project_id: UUID,
        character_id: UUID,
        payload: CharacterUpdatePayload,
        db: Session = Depends(get_db),
    ) -> CharacterResponse:
        ensure_project_exists(db, project_id)
        current = CharacterRepository(db).get(character_id)
        if current is None or str(current.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="character 不存在")
        row = CharacterRepository(db).update(
            character_id,
            name=payload.name,
            role_type=payload.role_type,
            age=payload.age,
            faction=payload.faction,
            profile_json=payload.profile_json,
            speech_style_json=payload.speech_style_json,
            arc_status_json=payload.arc_status_json,
            is_canonical=payload.is_canonical,
            version=payload.version,
        )
        return CharacterResponse(**_serialize_character(row))

    @app.delete(
        "/v2/projects/{project_id}/characters/{character_id}",
        tags=["Story Assets"],
        summary="删除角色",
        description="删除指定角色。",
    )
    def delete_character(project_id: UUID, character_id: UUID, db: Session = Depends(get_db)) -> dict:
        ensure_project_exists(db, project_id)
        current = CharacterRepository(db).get(character_id)
        if current is None or str(current.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="character 不存在")
        CharacterRepository(db).delete(character_id)
        return {"ok": True, "id": str(character_id)}

    @app.post(
        "/v2/projects/{project_id}/world-entries",
        response_model=WorldEntryResponse,
        tags=["Story Assets"],
        summary="新增世界观条目",
        description="创建世界观条目（地点/组织/规则等）。",
    )
    def create_world_entry(
        project_id: UUID,
        payload: WorldEntryCreatePayload,
        db: Session = Depends(get_db),
    ) -> WorldEntryResponse:
        ensure_project_exists(db, project_id)
        row = WorldEntryRepository(db).create(
            project_id=project_id,
            entry_type=payload.entry_type,
            title=payload.title,
            content=payload.content,
            metadata_json=payload.metadata_json,
            is_canonical=payload.is_canonical,
        )
        return WorldEntryResponse(**_serialize_world_entry(row))

    @app.get(
        "/v2/projects/{project_id}/world-entries",
        tags=["Story Assets"],
        summary="查询世界观条目",
        description="按项目查询世界观条目列表。",
    )
    def list_world_entries(
        project_id: UUID,
        canonical_only: bool = False,
        limit: int = 200,
        db: Session = Depends(get_db),
    ) -> dict:
        ensure_project_exists(db, project_id)
        rows = WorldEntryRepository(db).list_by_project(
            project_id=project_id,
            canonical_only=canonical_only,
            limit=max(1, min(limit, 500)),
        )
        return {"items": [_serialize_world_entry(row) for row in rows]}

    @app.get(
        "/v2/projects/{project_id}/world-entries/{entry_id}",
        response_model=WorldEntryResponse,
        tags=["Story Assets"],
        summary="查询世界观条目详情",
        description="按条目 ID 查询。",
    )
    def get_world_entry(project_id: UUID, entry_id: UUID, db: Session = Depends(get_db)) -> WorldEntryResponse:
        ensure_project_exists(db, project_id)
        row = WorldEntryRepository(db).get(entry_id)
        if row is None or str(row.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="world_entry 不存在")
        return WorldEntryResponse(**_serialize_world_entry(row))

    @app.patch(
        "/v2/projects/{project_id}/world-entries/{entry_id}",
        response_model=WorldEntryResponse,
        tags=["Story Assets"],
        summary="更新世界观条目",
        description="局部更新世界观条目。",
    )
    def update_world_entry(
        project_id: UUID,
        entry_id: UUID,
        payload: WorldEntryUpdatePayload,
        db: Session = Depends(get_db),
    ) -> WorldEntryResponse:
        ensure_project_exists(db, project_id)
        current = WorldEntryRepository(db).get(entry_id)
        if current is None or str(current.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="world_entry 不存在")
        row = WorldEntryRepository(db).update(
            entry_id,
            entry_type=payload.entry_type,
            title=payload.title,
            content=payload.content,
            metadata_json=payload.metadata_json,
            is_canonical=payload.is_canonical,
            version=payload.version,
        )
        return WorldEntryResponse(**_serialize_world_entry(row))

    @app.delete(
        "/v2/projects/{project_id}/world-entries/{entry_id}",
        tags=["Story Assets"],
        summary="删除世界观条目",
        description="删除指定条目。",
    )
    def delete_world_entry(project_id: UUID, entry_id: UUID, db: Session = Depends(get_db)) -> dict:
        ensure_project_exists(db, project_id)
        current = WorldEntryRepository(db).get(entry_id)
        if current is None or str(current.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="world_entry 不存在")
        WorldEntryRepository(db).delete(entry_id)
        return {"ok": True, "id": str(entry_id)}

    @app.post(
        "/v2/projects/{project_id}/timeline-events",
        response_model=TimelineEventResponse,
        tags=["Story Assets"],
        summary="新增时间线事件",
        description="新增剧情时间线事件。",
    )
    def create_timeline_event(
        project_id: UUID,
        payload: TimelineEventCreatePayload,
        db: Session = Depends(get_db),
    ) -> TimelineEventResponse:
        ensure_project_exists(db, project_id)
        row = TimelineEventRepository(db).create(
            project_id=project_id,
            chapter_no=payload.chapter_no,
            event_title=payload.event_title,
            event_desc=payload.event_desc,
            location=payload.location,
            involved_characters=payload.involved_characters,
            causal_links=payload.causal_links,
        )
        return TimelineEventResponse(**_serialize_timeline_event(row))

    @app.get(
        "/v2/projects/{project_id}/timeline-events",
        tags=["Story Assets"],
        summary="查询时间线事件",
        description="按项目查询时间线事件，可按 chapter_no 过滤。",
    )
    def list_timeline_events(
        project_id: UUID,
        chapter_no: int | None = None,
        limit: int = 300,
        db: Session = Depends(get_db),
    ) -> dict:
        ensure_project_exists(db, project_id)
        rows = TimelineEventRepository(db).list_by_project(
            project_id=project_id,
            chapter_no=chapter_no,
            limit=max(1, min(limit, 1000)),
        )
        return {"items": [_serialize_timeline_event(row) for row in rows]}

    @app.get(
        "/v2/projects/{project_id}/timeline-events/{event_id}",
        response_model=TimelineEventResponse,
        tags=["Story Assets"],
        summary="查询时间线事件详情",
        description="按事件 ID 查询。",
    )
    def get_timeline_event(project_id: UUID, event_id: UUID, db: Session = Depends(get_db)) -> TimelineEventResponse:
        ensure_project_exists(db, project_id)
        row = TimelineEventRepository(db).get(event_id)
        if row is None or str(row.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="timeline_event 不存在")
        return TimelineEventResponse(**_serialize_timeline_event(row))

    @app.patch(
        "/v2/projects/{project_id}/timeline-events/{event_id}",
        response_model=TimelineEventResponse,
        tags=["Story Assets"],
        summary="更新时间线事件",
        description="局部更新时间线事件字段。",
    )
    def update_timeline_event(
        project_id: UUID,
        event_id: UUID,
        payload: TimelineEventUpdatePayload,
        db: Session = Depends(get_db),
    ) -> TimelineEventResponse:
        ensure_project_exists(db, project_id)
        current = TimelineEventRepository(db).get(event_id)
        if current is None or str(current.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="timeline_event 不存在")
        row = TimelineEventRepository(db).update(
            event_id,
            chapter_no=payload.chapter_no,
            event_title=payload.event_title,
            event_desc=payload.event_desc,
            location=payload.location,
            involved_characters=payload.involved_characters,
            causal_links=payload.causal_links,
        )
        return TimelineEventResponse(**_serialize_timeline_event(row))

    @app.delete(
        "/v2/projects/{project_id}/timeline-events/{event_id}",
        tags=["Story Assets"],
        summary="删除时间线事件",
        description="删除指定时间线事件。",
    )
    def delete_timeline_event(project_id: UUID, event_id: UUID, db: Session = Depends(get_db)) -> dict:
        ensure_project_exists(db, project_id)
        current = TimelineEventRepository(db).get(event_id)
        if current is None or str(current.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="timeline_event 不存在")
        TimelineEventRepository(db).delete(event_id)
        return {"ok": True, "id": str(event_id)}

    @app.post(
        "/v2/projects/{project_id}/foreshadowings",
        response_model=ForeshadowingResponse,
        tags=["Story Assets"],
        summary="新增伏笔",
        description="创建伏笔条目（open/resolved）。",
    )
    def create_foreshadowing(
        project_id: UUID,
        payload: ForeshadowingCreatePayload,
        db: Session = Depends(get_db),
    ) -> ForeshadowingResponse:
        ensure_project_exists(db, project_id)
        row = ForeshadowingRepository(db).create(
            project_id=project_id,
            setup_chapter_no=payload.setup_chapter_no,
            setup_text=payload.setup_text,
            expected_payoff=payload.expected_payoff,
            payoff_chapter_no=payload.payoff_chapter_no,
            payoff_text=payload.payoff_text,
            status=payload.status,
        )
        return ForeshadowingResponse(**_serialize_foreshadowing(row))

    @app.get(
        "/v2/projects/{project_id}/foreshadowings",
        tags=["Story Assets"],
        summary="查询伏笔列表",
        description="按项目查询伏笔，可按 status 过滤。",
    )
    def list_foreshadowings(
        project_id: UUID,
        status: str | None = None,
        limit: int = 300,
        db: Session = Depends(get_db),
    ) -> dict:
        ensure_project_exists(db, project_id)
        rows = ForeshadowingRepository(db).list_by_project(
            project_id=project_id,
            status=status,
            limit=max(1, min(limit, 1000)),
        )
        return {"items": [_serialize_foreshadowing(row) for row in rows]}

    @app.get(
        "/v2/projects/{project_id}/foreshadowings/{foreshadowing_id}",
        response_model=ForeshadowingResponse,
        tags=["Story Assets"],
        summary="查询伏笔详情",
        description="按伏笔 ID 查询。",
    )
    def get_foreshadowing(
        project_id: UUID,
        foreshadowing_id: UUID,
        db: Session = Depends(get_db),
    ) -> ForeshadowingResponse:
        ensure_project_exists(db, project_id)
        row = ForeshadowingRepository(db).get(foreshadowing_id)
        if row is None or str(row.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="foreshadowing 不存在")
        return ForeshadowingResponse(**_serialize_foreshadowing(row))

    @app.patch(
        "/v2/projects/{project_id}/foreshadowings/{foreshadowing_id}",
        response_model=ForeshadowingResponse,
        tags=["Story Assets"],
        summary="更新伏笔",
        description="局部更新伏笔状态与回收信息。",
    )
    def update_foreshadowing(
        project_id: UUID,
        foreshadowing_id: UUID,
        payload: ForeshadowingUpdatePayload,
        db: Session = Depends(get_db),
    ) -> ForeshadowingResponse:
        ensure_project_exists(db, project_id)
        current = ForeshadowingRepository(db).get(foreshadowing_id)
        if current is None or str(current.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="foreshadowing 不存在")
        row = ForeshadowingRepository(db).update(
            foreshadowing_id,
            setup_chapter_no=payload.setup_chapter_no,
            setup_text=payload.setup_text,
            expected_payoff=payload.expected_payoff,
            payoff_chapter_no=payload.payoff_chapter_no,
            payoff_text=payload.payoff_text,
            status=payload.status,
        )
        return ForeshadowingResponse(**_serialize_foreshadowing(row))

    @app.delete(
        "/v2/projects/{project_id}/foreshadowings/{foreshadowing_id}",
        tags=["Story Assets"],
        summary="删除伏笔",
        description="删除指定伏笔。",
    )
    def delete_foreshadowing(project_id: UUID, foreshadowing_id: UUID, db: Session = Depends(get_db)) -> dict:
        ensure_project_exists(db, project_id)
        current = ForeshadowingRepository(db).get(foreshadowing_id)
        if current is None or str(current.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="foreshadowing 不存在")
        ForeshadowingRepository(db).delete(foreshadowing_id)
        return {"ok": True, "id": str(foreshadowing_id)}

    @app.post(
        "/v2/projects/{project_id}/chapters",
        tags=["Chapters"],
        summary="手动创建章节",
        description="创建新章节（自动分配 chapter_no），并生成首个版本快照。",
    )
    def create_chapter(
        project_id: UUID,
        payload: ChapterCreatePayload,
        db: Session = Depends(get_db),
    ) -> dict:
        ensure_project_exists(db, project_id)
        repo = ChapterRepository(db)
        row = repo.create(
            project_id=project_id,
            title=payload.title,
            content=payload.content,
        )
        if payload.summary is not None:
            row.summary = payload.summary
            db.commit()
            db.refresh(row)
        repo.create_version(
            chapter_id=row.id,
            content=row.content,
            summary=row.summary,
            source_agent="manual_editor",
            source_workflow="chapter_manual_create",
        )
        return _serialize_chapter(row)

    @app.get(
        "/v2/projects/{project_id}/chapters",
        tags=["Chapters"],
        summary="查询章节列表",
        description="按章节号升序返回章节列表。",
    )
    def list_chapters(
        project_id: UUID,
        include_content: bool = False,
        db: Session = Depends(get_db),
    ) -> dict:
        ensure_project_exists(db, project_id)
        rows = list(ChapterRepository(db).list_by_project(project_id))
        items = [_serialize_chapter(row) for row in rows]
        if not include_content:
            for item in items:
                item["content"] = None
        return {"items": items}

    @app.get(
        "/v2/projects/{project_id}/chapters/{chapter_id}",
        tags=["Chapters"],
        summary="查询章节详情",
        description="按 chapter_id 查询章节。",
    )
    def get_chapter(project_id: UUID, chapter_id: UUID, db: Session = Depends(get_db)) -> dict:
        ensure_project_exists(db, project_id)
        row = ChapterRepository(db).get(chapter_id)
        if row is None or str(row.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="chapter 不存在")
        return _serialize_chapter(row)

    @app.patch(
        "/v2/projects/{project_id}/chapters/{chapter_id}",
        tags=["Chapters"],
        summary="更新章节",
        description="更新章节内容/标题/摘要/状态，并保留版本历史。",
    )
    def update_chapter(
        project_id: UUID,
        chapter_id: UUID,
        payload: ChapterUpdatePayload,
        db: Session = Depends(get_db),
    ) -> dict:
        ensure_project_exists(db, project_id)
        repo = ChapterRepository(db)
        row = repo.get(chapter_id)
        if row is None or str(row.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="chapter 不存在")

        if payload.content is not None:
            row = repo.update_content(
                chapter_id=chapter_id,
                content=payload.content,
                summary=payload.summary,
            )
        else:
            if payload.title is not None:
                row.title = payload.title
            if payload.summary is not None:
                row.summary = payload.summary
            if payload.status is not None:
                row.status = payload.status
            db.commit()
            db.refresh(row)
            repo.create_version(
                chapter_id=row.id,
                content=row.content,
                summary=row.summary,
                source_agent="manual_editor",
                source_workflow="chapter_manual_update",
            )

        if payload.title is not None and row.title != payload.title:
            row.title = payload.title
            db.commit()
            db.refresh(row)
        if payload.status is not None and str(row.status.value if hasattr(row.status, "value") else row.status) != payload.status:
            row.status = payload.status
            db.commit()
            db.refresh(row)
        return _serialize_chapter(row)

    @app.post(
        "/v2/projects/{project_id}/chapters/{chapter_id}/publish",
        response_model=ChapterPublishResponse,
        tags=["Chapters"],
        summary="发布章节",
        description="将章节状态设置为 published。",
    )
    def publish_chapter(project_id: UUID, chapter_id: UUID, db: Session = Depends(get_db)) -> ChapterPublishResponse:
        ensure_project_exists(db, project_id)
        repo = ChapterRepository(db)
        row = repo.get(chapter_id)
        if row is None or str(row.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="chapter 不存在")
        row = repo.publish(chapter_id)
        return ChapterPublishResponse(
            ok=True,
            chapter_id=str(row.id),
            status=str(row.status.value if hasattr(row.status, "value") else row.status),
        )

    @app.get(
        "/v2/projects/{project_id}/chapters/{chapter_id}/versions",
        tags=["Chapters"],
        summary="查询章节版本",
        description="返回章节的版本历史（倒序）。",
    )
    def list_chapter_versions(project_id: UUID, chapter_id: UUID, db: Session = Depends(get_db)) -> dict:
        ensure_project_exists(db, project_id)
        repo = ChapterRepository(db)
        chapter = repo.get(chapter_id)
        if chapter is None or str(chapter.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="chapter 不存在")
        rows = list(repo.list_versions(chapter_id))
        return {"items": [_serialize_chapter_version(row) for row in rows]}

    @app.delete(
        "/v2/projects/{project_id}/chapters/{chapter_id}",
        tags=["Chapters"],
        summary="删除章节",
        description="删除章节及关联版本。",
    )
    def delete_chapter(project_id: UUID, chapter_id: UUID, req: Request, db: Session = Depends(get_db)) -> dict:
        ensure_project_exists(db, project_id)
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        repo = ChapterRepository(db)
        chapter = repo.get(chapter_id)
        if chapter is None or str(chapter.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="chapter 不存在")
        repo.delete(chapter_id)
        AuditService(repo=AuditEventRepository(db)).log(
            action="chapter_delete",
            resource_type="chapter",
            resource_id=str(chapter_id),
            project_id=project_id,
            user_id=UUID(str(user["id"])),
            payload_json={"chapter_no": int(chapter.chapter_no)},
        )
        return {"ok": True, "chapter_id": str(chapter_id)}

    @app.post(
        "/v2/projects/{project_id}/chapters/{chapter_id}/rollback/{version_no}",
        tags=["Chapters"],
        summary="回滚章节到指定版本",
        description="回滚前会自动备份当前版本。",
    )
    def rollback_chapter(
        project_id: UUID,
        chapter_id: UUID,
        version_no: int,
        req: Request,
        db: Session = Depends(get_db),
    ) -> dict:
        ensure_project_exists(db, project_id)
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        repo = ChapterRepository(db)
        chapter = repo.get(chapter_id)
        if chapter is None or str(chapter.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="chapter 不存在")
        rolled = repo.rollback_to_version(chapter_id, version_no)
        if rolled is None:
            raise HTTPException(status_code=404, detail="version 不存在")
        AuditService(repo=AuditEventRepository(db)).log(
            action="chapter_rollback",
            resource_type="chapter",
            resource_id=str(chapter_id),
            project_id=project_id,
            user_id=UUID(str(user["id"])),
            payload_json={"version_no": int(version_no)},
        )
        return _serialize_chapter(rolled)

    # ---------------- v1: 可控兼容入口（默认关闭） ----------------
    if orchestrator_cfg.api_v1_enabled:
        @app.post(
            "/v1/projects/{project_id}/chapters/generate",
            response_model=ChapterGenerateResponse,
            tags=["V1 Compatibility"],
            summary="生成单章（v1 兼容接口）",
            description="同步生成章节并写入长期记忆。仅在启用 v1 兼容开关时可见。",
        )
        def generate_chapter(
            project_id: UUID,
            payload: ChapterGeneratePayload,
            req: Request,
            db: Session = Depends(get_db),
        ) -> ChapterGenerateResponse:
            workflow = req.app.state.workflow_factory(db)
            try:
                result = workflow.run(
                    ChapterGenerationRequest(
                        project_id=project_id,
                        writing_goal=payload.writing_goal,
                        chapter_no=payload.chapter_no,
                        target_words=payload.target_words,
                        style_hint=payload.style_hint,
                        include_memory_top_k=payload.include_memory_top_k,
                        context_token_budget=payload.context_token_budget,
                        temperature=payload.temperature,
                        chat_turns=payload.chat_turns,
                        working_notes=payload.working_notes,
                    )
                )
            except ChapterGenerationWorkflowError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc

            return ChapterGenerateResponse(
                trace_id=result.trace_id,
                agent_run_id=result.agent_run_id,
                mock_mode=result.mock_mode,
                chapter=result.chapter,
                memory_ingestion=result.memory_ingestion,
                writer_structured=result.writer_structured,
                warnings=result.warnings,
                skill_runs=result.skill_runs,
            )

    # ---------------- v2: 异步编排入口 ----------------
    @app.post(
        "/v2/projects/{project_id}/writing/runs",
        response_model=WorkflowRunCreateResponse,
        tags=["Writing Runs"],
        summary="创建写作 Run（主入口）",
        description=(
            "创建异步写作任务。默认 workflow_type=writing_full，"
            "会执行完整链路（大纲、章节、一致性审查、修订）。"
        ),
    )
    def create_writing_run(
        project_id: UUID,
        payload: WorkflowRunCreatePayload,
        req: Request,
        db: Session = Depends(get_db),
    ) -> WorkflowRunCreateResponse:
        service = req.app.state.orchestrator_factory(db)
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        chat_turns = payload.chat_turns
        if payload.session_id is not None:
            session_repo = SessionRepository(db)
            session_row = session_repo.get_session(payload.session_id)
            if session_row is None or str(session_row.project_id) != str(project_id):
                raise HTTPException(status_code=404, detail="session 不存在")
            if chat_turns is None:
                chat_turns = SessionService(repo=session_repo).to_chat_turns(
                    session_id=payload.session_id,
                    max_messages=40,
                )
        try:
            result = service.create_run(
                WorkflowRunRequest(
                    project_id=project_id,
                    workflow_type=payload.workflow_type,
                    writing_goal=payload.writing_goal,
                    chapter_no=payload.chapter_no,
                    target_words=payload.target_words,
                    style_hint=payload.style_hint,
                    include_memory_top_k=payload.include_memory_top_k,
                    context_token_budget=payload.context_token_budget,
                    temperature=payload.temperature,
                    chat_turns=chat_turns,
                    working_notes=payload.working_notes,
                    session_id=str(payload.session_id) if payload.session_id is not None else None,
                    idempotency_key=payload.idempotency_key,
                    user_id=str(user["id"]),
                )
            )
            if payload.session_id is not None:
                SessionRepository(db).update_session(
                    payload.session_id,
                    linked_workflow_run_id=UUID(result.run_id),
                )
            if req.app.state.orchestrator_cfg.enable_auto_worker:
                service.process_once(limit=1)
            return WorkflowRunCreateResponse(**result.__dict__)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get(
        "/v2/writing/runs/{run_id}",
        tags=["Writing Runs"],
        summary="查询写作 Run 详情",
        description="返回 run 状态、步骤执行明细、检索回放、错误信息与产出摘要。",
    )
    def get_writing_run(run_id: UUID, req: Request, db: Session = Depends(get_db)) -> dict:
        service = req.app.state.orchestrator_factory(db)
        detail = service.get_run_detail(run_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="run 不存在")
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(
            db=db,
            project_id=UUID(str(detail["project_id"])),
            user=user,
            min_role="viewer",
        )
        return detail

    @app.websocket("/v2/writing/runs/{run_id}/ws")
    async def stream_writing_run_events(run_id: UUID, websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            token = _extract_ws_bearer_token(websocket)
        except AuthError:
            await websocket.close(code=4401, reason="missing_or_invalid_token")
            return

        nonlocal session_factory
        if session_factory is None:
            session_factory = create_session_factory()
            app.state.session_factory = session_factory

        # 初始鉴权 + run 可见性检查。
        db = session_factory()
        try:
            auth = _build_auth_service(db)
            try:
                user = auth.authenticate_access_token(token)
            except AuthError:
                await websocket.close(code=4401, reason="invalid_access_token")
                return

            service = websocket.app.state.orchestrator_factory(db)
            detail = service.get_run_detail(run_id)
            if detail is None:
                await websocket.close(code=4404, reason="run_not_found")
                return
            ensure_project_role(
                db=db,
                project_id=UUID(str(detail["project_id"])),
                user=user,
                min_role="viewer",
            )
        except HTTPException:
            await websocket.close(code=4403, reason="forbidden")
            return
        finally:
            db.close()

        cursor_raw = str(websocket.query_params.get("cursor") or "").strip()
        try:
            cursor = max(0, int(cursor_raw or "0"))
        except ValueError:
            cursor = 0

        heartbeat_seconds = 12.0
        poll_seconds = 1.0
        last_sent_at = perf_counter()

        try:
            while True:
                db = session_factory()
                try:
                    service = websocket.app.state.orchestrator_factory(db)
                    detail = service.get_run_detail(run_id)
                    if detail is None:
                        await websocket.close(code=4404, reason="run_not_found")
                        return
                    ensure_project_role(
                        db=db,
                        project_id=UUID(str(detail["project_id"])),
                        user=user,
                        min_role="viewer",
                    )
                    events = build_run_events(detail)
                except HTTPException:
                    await websocket.close(code=4403, reason="forbidden")
                    return
                finally:
                    db.close()

                pending = events_since_cursor(events, cursor)
                if pending:
                    for event in pending:
                        await websocket.send_json(event)
                        cursor = int(event.get("seq") or cursor)
                        last_sent_at = perf_counter()
                else:
                    now = perf_counter()
                    if now - last_sent_at >= heartbeat_seconds:
                        hb_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                        await websocket.send_json(
                            {
                                "event_id": f"{run_id}:heartbeat:{cursor}:{int(now)}",
                                "run_id": str(run_id),
                                "seq": cursor,
                                "event_type": "heartbeat",
                                "ts": hb_ts,
                                "payload": {"cursor": cursor},
                                "trace_id": detail.get("trace_id"),
                            }
                        )
                        last_sent_at = now

                if terminal_status_reached(detail) and cursor >= last_seq(events):
                    await websocket.close(code=1000, reason="run_terminal")
                    return

                await asyncio.sleep(poll_seconds)
        except WebSocketDisconnect:
            return
        except Exception:
            await websocket.close(code=1011, reason="internal_error")
            return

    @app.post(
        "/v2/writing/runs/{run_id}/cancel",
        tags=["Writing Runs"],
        summary="取消写作 Run",
        description="取消当前 run，并将未完成步骤置为 cancelled。",
    )
    def cancel_writing_run(run_id: UUID, req: Request, db: Session = Depends(get_db)) -> dict:
        service = req.app.state.orchestrator_factory(db)
        detail = service.get_run_detail(run_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="run 不存在")
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(
            db=db,
            project_id=UUID(str(detail["project_id"])),
            user=user,
            min_role="editor",
        )
        ok = service.cancel_run(run_id)
        if not ok:
            raise HTTPException(status_code=404, detail="run 不存在")
        return {"ok": True, "run_id": str(run_id), "status": "cancelled"}

    @app.post(
        "/v2/writing/runs/{run_id}/retry",
        tags=["Writing Runs"],
        summary="重试失败/取消 run",
        description="仅 failed/cancelled 状态可重试，幂等恢复后重新入队。",
    )
    def retry_writing_run(run_id: UUID, req: Request, db: Session = Depends(get_db)) -> dict:
        service = req.app.state.orchestrator_factory(db)
        detail = service.get_run_detail(run_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="run 不存在")
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(
            db=db,
            project_id=UUID(str(detail["project_id"])),
            user=user,
            min_role="editor",
        )
        ok = service.retry_run(run_id)
        if not ok:
            raise HTTPException(status_code=400, detail="仅 failed/cancelled 状态可重试，或 run 不存在")
        if req.app.state.orchestrator_cfg.enable_auto_worker:
            service.process_once(limit=1)
        return {"ok": True, "run_id": str(run_id), "status": "queued"}

    @app.post(
        "/v2/projects/{project_id}/workflows/{workflow_type}/runs",
        response_model=WorkflowRunCreateResponse,
        tags=["Workflows"],
        summary="创建单工作流 Run",
        description=(
            "按指定 workflow_type 触发单工作流。"
            "适用于只跑 chapter_generation/revision 等局部流程。"
        ),
    )
    def create_single_workflow_run(
        project_id: UUID,
        workflow_type: str,
        payload: WorkflowRunCreatePayload,
        req: Request,
        db: Session = Depends(get_db),
    ) -> WorkflowRunCreateResponse:
        service = req.app.state.orchestrator_factory(db)
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        chat_turns = payload.chat_turns
        if payload.session_id is not None:
            session_repo = SessionRepository(db)
            session_row = session_repo.get_session(payload.session_id)
            if session_row is None or str(session_row.project_id) != str(project_id):
                raise HTTPException(status_code=404, detail="session 不存在")
            if chat_turns is None:
                chat_turns = SessionService(repo=session_repo).to_chat_turns(
                    session_id=payload.session_id,
                    max_messages=40,
                )
        try:
            result = service.create_run(
                WorkflowRunRequest(
                    project_id=project_id,
                    workflow_type=workflow_type,
                    writing_goal=payload.writing_goal,
                    chapter_no=payload.chapter_no,
                    target_words=payload.target_words,
                    style_hint=payload.style_hint,
                    include_memory_top_k=payload.include_memory_top_k,
                    context_token_budget=payload.context_token_budget,
                    temperature=payload.temperature,
                    chat_turns=chat_turns,
                    working_notes=payload.working_notes,
                    session_id=str(payload.session_id) if payload.session_id is not None else None,
                    idempotency_key=payload.idempotency_key,
                    user_id=str(user["id"]),
                )
            )
            if payload.session_id is not None:
                SessionRepository(db).update_session(
                    payload.session_id,
                    linked_workflow_run_id=UUID(result.run_id),
                )
            if req.app.state.orchestrator_cfg.enable_auto_worker:
                service.process_once(limit=1)
            return WorkflowRunCreateResponse(**result.__dict__)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get(
        "/v2/projects/{project_id}/outlines/latest",
        tags=["Outlines"],
        summary="获取最新大纲",
        description="优先返回 active 大纲；若无 active，则回退到最新版本。",
    )
    def get_latest_outline(project_id: UUID, db: Session = Depends(get_db)) -> dict:
        repo = OutlineRepository(db)
        row = repo.get_active(project_id=project_id) or repo.get_latest(project_id=project_id)
        if row is None:
            raise HTTPException(status_code=404, detail="outline 不存在")
        return {
            "id": str(row.id),
            "project_id": str(row.project_id),
            "version_no": int(row.version_no),
            "title": row.title,
            "content": row.content,
            "structure_json": dict(row.structure_json or {}),
            "source_agent": row.source_agent,
            "source_workflow": row.source_workflow,
            "trace_id": row.trace_id,
            "is_active": bool(row.is_active),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @app.get(
        "/v2/projects/{project_id}/consistency-reports",
        tags=["Consistency"],
        summary="查询一致性报告",
        description="按项目拉取一致性审查报告列表，支持 limit 参数。",
    )
    def list_consistency_reports(project_id: UUID, limit: int = 20, db: Session = Depends(get_db)) -> dict:
        repo = ConsistencyReportRepository(db)
        rows = repo.list_by_project(project_id=project_id, limit=max(1, min(limit, 200)))
        return {
            "items": [
                {
                    "id": str(row.id),
                    "project_id": str(row.project_id),
                    "chapter_id": str(row.chapter_id) if row.chapter_id is not None else None,
                    "chapter_version_id": int(row.chapter_version_id) if row.chapter_version_id is not None else None,
                    "status": str(row.status),
                    "score": float(row.score) if row.score is not None else None,
                    "summary": row.summary,
                    "issues_json": list(row.issues_json or []),
                    "recommendations_json": list(row.recommendations_json or []),
                    "trace_id": row.trace_id,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ]
        }

    @app.post(
        "/v2/retrieval/feedback",
        response_model=RetrievalFeedbackResponse,
        tags=["Retrieval"],
        summary="写入检索反馈",
        description="记录检索点击反馈，用于在线评测与检索排序优化。",
    )
    def retrieval_feedback(
        payload: RetrievalFeedbackPayload,
        req: Request,
        db: Session = Depends(get_db),
    ) -> RetrievalFeedbackResponse:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(db=db, project_id=payload.project_id, user=user, min_role="viewer")
        search = req.app.state.search_factory(db)
        ok = search.record_feedback(
            project_id=payload.project_id,
            request_id=payload.request_id,
            user_id=str(user["id"]),
            clicked_doc_id=payload.clicked_doc_id,
            clicked=payload.clicked,
        )
        return RetrievalFeedbackResponse(ok=bool(ok))

    @app.post(
        "/v2/projects/{project_id}/evaluation/feedback",
        response_model=EvaluationFeedbackResponse,
        tags=["Evaluation"],
        summary="写入统一评测反馈",
        description=(
            "统一处理 retrieval/writing 两类反馈。"
            "retrieval 需要 request_id；writing 需要 workflow_run_id 与 score。"
        ),
    )
    def evaluation_feedback(
        project_id: UUID,
        payload: EvaluationFeedbackPayload,
        req: Request,
        db: Session = Depends(get_db),
    ) -> EvaluationFeedbackResponse:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(db=db, project_id=project_id, user=user, min_role="viewer")
        evaluation_service = req.app.state.evaluation_factory(db)
        try:
            evaluation_service.validate_feedback_payload(
                payload.model_dump(mode="json", exclude_none=True)
            )
        except SchemaValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        evaluation_type = str(payload.evaluation_type).strip().lower()
        if evaluation_type == "retrieval":
            if not payload.request_id:
                raise HTTPException(status_code=400, detail="retrieval 反馈必须提供 request_id")
            search = req.app.state.search_factory(db)
            ok = search.record_feedback(
                project_id=project_id,
                request_id=payload.request_id,
                user_id=str(user["id"]),
                clicked_doc_id=payload.clicked_doc_id,
                clicked=bool(payload.clicked if payload.clicked is not None else True),
            )
            return EvaluationFeedbackResponse(
                ok=bool(ok),
                evaluation_type="retrieval",
                detail=None if ok else "request_id 不存在或反馈写入失败",
            )

        if evaluation_type == "writing":
            if payload.workflow_run_id is None:
                raise HTTPException(status_code=400, detail="writing 反馈必须提供 workflow_run_id")
            if payload.score is None:
                raise HTTPException(status_code=400, detail="writing 反馈必须提供 score")

            ok = evaluation_service.record_writing_feedback(
                project_id=project_id,
                workflow_run_id=payload.workflow_run_id,
                score=float(payload.score),
                payload_json={
                    "comment": payload.comment,
                    "user_id": str(user["id"]),
                },
            )
            return EvaluationFeedbackResponse(
                ok=bool(ok),
                evaluation_type="writing",
                detail=None if ok else "workflow_run_id 未找到对应 writing evaluation run",
            )

        raise HTTPException(status_code=400, detail="evaluation_type 非法，必须是 retrieval 或 writing")

    @app.get(
        "/v2/projects/{project_id}/evaluation/daily",
        tags=["Evaluation"],
        summary="查询评测日报",
        description="返回日维度评测指标，可按 evaluation_type 与 days 过滤。",
    )
    def list_evaluation_daily(
        project_id: UUID,
        req: Request,
        evaluation_type: str | None = None,
        days: int = 30,
        db: Session = Depends(get_db),
    ) -> dict:
        service = req.app.state.evaluation_factory(db)
        normalized_type = None if evaluation_type in {None, "", "all"} else str(evaluation_type).strip().lower()
        items = service.list_daily(
            project_id=project_id,
            evaluation_type=normalized_type,
            days=max(1, min(int(days), 180)),
        )
        return {
            "items": [
                {
                    "project_id": item.project_id,
                    "metric_date": item.metric_date,
                    "evaluation_type": item.evaluation_type,
                    "metric_key": item.metric_key,
                    "metric_value": item.metric_value,
                    "samples": item.samples,
                }
                for item in items
            ]
        }

    @app.get(
        "/v2/projects/{project_id}/evaluation/runs/{run_id}",
        tags=["Evaluation"],
        summary="查询评测 Run 详情",
        description="返回评测 run 的汇总结果与事件明细。",
    )
    def get_evaluation_run_detail(
        project_id: UUID,
        run_id: UUID,
        req: Request,
        db: Session = Depends(get_db),
    ) -> dict:
        service = req.app.state.evaluation_factory(db)
        detail = service.get_run_detail(run_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="evaluation run 不存在")
        if str(detail.get("project_id")) != str(project_id):
            raise HTTPException(status_code=404, detail="evaluation run 不存在")
        return detail

    @app.post(
        "/v2/projects/{project_id}/users/{user_id}/preferences",
        response_model=UserPreferencesResponse,
        tags=["Users"],
        summary="更新用户偏好并重建偏好记忆",
        description=(
            "更新 users.preferences，并触发 user_preference 记忆重建，"
            "让偏好立刻进入检索与写作上下文。"
        ),
    )
    def update_user_preferences(
        project_id: UUID,
        user_id: UUID,
        payload: UserPreferencesPayload,
        req: Request,
        db: Session = Depends(get_db),
    ) -> UserPreferencesResponse:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        if not _is_system_admin(user) and str(user_id) != str(user["id"]):
            raise HTTPException(status_code=403, detail="仅可更新自己的偏好")
        project = ProjectRepository(db).get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project 不存在")

        row = UserRepository(db).update_preferences(user_id, dict(payload.preferences or {}))
        if row is None:
            raise HTTPException(status_code=404, detail="user 不存在")

        if project.owner_user_id is not None and str(project.owner_user_id) != str(user_id):
            raise HTTPException(status_code=400, detail="user 不是该项目 owner")

        try:
            rebuilt = _rebuild_user_preferences_memory(
                db=db,
                project_id=project_id,
                user_id=user_id,
                preferences=dict(payload.preferences or {}),
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"偏好记忆重建失败: {exc}") from exc

        return UserPreferencesResponse(
            ok=True,
            user_id=str(row.id),
            rebuild_chunks=rebuilt,
        )

    @app.get(
        "/v2/projects/{project_id}/members",
        tags=["Projects"],
        summary="项目成员列表",
        description="返回项目成员及角色。",
    )
    def list_project_members(project_id: UUID, req: Request, db: Session = Depends(get_db)) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(db=db, project_id=project_id, user=user, min_role="viewer")
        rows = ProjectMembershipRepository(db).list_by_project(project_id=project_id, include_disabled=True)
        return {"items": [_serialize_project_membership(row) for row in rows]}

    @app.put(
        "/v2/projects/{project_id}/members/{member_user_id}",
        tags=["Projects"],
        summary="设置项目成员角色",
        description="owner 可新增/更新成员角色与状态。",
    )
    def upsert_project_member(
        project_id: UUID,
        member_user_id: UUID,
        payload: ProjectMemberUpsertPayload,
        req: Request,
        db: Session = Depends(get_db),
    ) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(db=db, project_id=project_id, user=user, min_role="owner")
        if str(member_user_id) != str(payload.user_id):
            raise HTTPException(status_code=400, detail="path user_id 与 payload.user_id 不一致")
        if UserRepository(db).get(member_user_id) is None:
            raise HTTPException(status_code=404, detail="user 不存在")
        row = ProjectMembershipRepository(db).create_or_update(
            project_id=project_id,
            user_id=member_user_id,
            role=payload.role,
            status=payload.status,
            invited_by=UUID(str(user["id"])),
            note=payload.note,
        )
        return _serialize_project_membership(row)

    @app.delete(
        "/v2/projects/{project_id}/members/{member_user_id}",
        tags=["Projects"],
        summary="移除项目成员",
        description="owner 可移除成员（不能移除最后一个 owner）。",
    )
    def delete_project_member(
        project_id: UUID,
        member_user_id: UUID,
        req: Request,
        db: Session = Depends(get_db),
    ) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(db=db, project_id=project_id, user=user, min_role="owner")
        membership_repo = ProjectMembershipRepository(db)
        target = membership_repo.get(project_id=project_id, user_id=member_user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="member 不存在")
        if str(target.role) == "owner":
            owners = [
                item
                for item in membership_repo.list_by_project(project_id=project_id, include_disabled=False)
                if str(item.role) == "owner"
            ]
            if len(owners) <= 1:
                raise HTTPException(status_code=400, detail="不能移除最后一个 owner")
        membership_repo.remove(project_id=project_id, user_id=member_user_id)
        return {"ok": True, "project_id": str(project_id), "user_id": str(member_user_id)}

    @app.post(
        "/v2/projects/{project_id}/sessions",
        tags=["Projects"],
        summary="创建会话",
        description="创建会话上下文，用于后续 writing run 自动注入短期记忆。",
    )
    def create_session(
        project_id: UUID,
        payload: SessionCreatePayload,
        req: Request,
        db: Session = Depends(get_db),
    ) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(db=db, project_id=project_id, user=user, min_role="editor")
        row = SessionService(repo=SessionRepository(db)).create(
            project_id=project_id,
            user_id=UUID(str(user["id"])),
            title=payload.title,
            metadata_json=payload.metadata_json,
        )
        return _serialize_session(row)

    @app.get(
        "/v2/projects/{project_id}/sessions",
        tags=["Projects"],
        summary="查询会话列表",
        description="按项目查询会话。",
    )
    def list_sessions(project_id: UUID, req: Request, db: Session = Depends(get_db)) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(db=db, project_id=project_id, user=user, min_role="viewer")
        rows = SessionRepository(db).list_sessions(project_id=project_id, limit=200)
        return {"items": [_serialize_session(row) for row in rows]}

    @app.post(
        "/v2/projects/{project_id}/sessions/{session_id}/messages",
        tags=["Projects"],
        summary="写入会话消息",
        description="向会话追加消息。",
    )
    def create_session_message(
        project_id: UUID,
        session_id: UUID,
        payload: SessionMessageCreatePayload,
        req: Request,
        db: Session = Depends(get_db),
    ) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(db=db, project_id=project_id, user=user, min_role="editor")
        session_repo = SessionRepository(db)
        session_row = session_repo.get_session(session_id)
        if session_row is None or str(session_row.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="session 不存在")
        row = session_repo.add_message(
            session_id=session_id,
            project_id=project_id,
            role=payload.role,
            content=payload.content,
            user_id=UUID(str(user["id"])),
            token_count=payload.token_count,
            metadata_json=payload.metadata_json,
        )
        return _serialize_session_message(row)

    @app.get(
        "/v2/projects/{project_id}/sessions/{session_id}/messages",
        tags=["Projects"],
        summary="查询会话消息",
        description="按时间正序返回会话消息。",
    )
    def list_session_messages(
        project_id: UUID,
        session_id: UUID,
        req: Request,
        limit: int = 200,
        db: Session = Depends(get_db),
    ) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(db=db, project_id=project_id, user=user, min_role="viewer")
        session_repo = SessionRepository(db)
        session_row = session_repo.get_session(session_id)
        if session_row is None or str(session_row.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="session 不存在")
        rows = session_repo.list_messages(session_id=session_id, limit=max(1, min(limit, 500)), ascending=True)
        return {"items": [_serialize_session_message(row) for row in rows]}

    @app.post(
        "/v2/projects/{project_id}/sessions/{session_id}/summarize",
        tags=["Projects"],
        summary="会话总结",
        description="生成并写回会话摘要。",
    )
    def summarize_session(
        project_id: UUID,
        session_id: UUID,
        payload: SessionSummarizePayload,
        req: Request,
        db: Session = Depends(get_db),
    ) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(db=db, project_id=project_id, user=user, min_role="viewer")
        session_repo = SessionRepository(db)
        session_row = session_repo.get_session(session_id)
        if session_row is None or str(session_row.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="session 不存在")
        summary = SessionService(repo=session_repo).summarize(
            session_id=session_id,
            max_items=payload.max_items,
        )
        row = session_repo.get_session(session_id)
        return {"ok": True, "summary": summary, "session": _serialize_session(row)}

    @app.post(
        "/v2/projects/{project_id}/sessions/{session_id}/link-run/{run_id}",
        tags=["Projects"],
        summary="关联会话与写作 run",
        description="将会话绑定到指定 run。",
    )
    def link_session_run(
        project_id: UUID,
        session_id: UUID,
        run_id: UUID,
        req: Request,
        db: Session = Depends(get_db),
    ) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(db=db, project_id=project_id, user=user, min_role="editor")
        orchestrator = req.app.state.orchestrator_factory(db)
        detail = orchestrator.get_run_detail(run_id)
        if detail is None or str(detail["project_id"]) != str(project_id):
            raise HTTPException(status_code=404, detail="run 不存在")
        session_repo = SessionRepository(db)
        row = session_repo.update_session(session_id, linked_workflow_run_id=run_id)
        if row is None or str(row.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="session 不存在")
        return {"ok": True, "session": _serialize_session(row)}

    @app.get(
        "/v2/projects/{project_id}/chapter-candidates",
        tags=["Chapters"],
        summary="查询候选稿",
        description="按项目查看候选稿列表。",
    )
    def list_chapter_candidates(
        project_id: UUID,
        req: Request,
        status: str | None = None,
        limit: int = 100,
        db: Session = Depends(get_db),
    ) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(db=db, project_id=project_id, user=user, min_role="viewer")
        rows = ChapterCandidateRepository(db).list_by_project(
            project_id=project_id,
            status=status,
            limit=max(1, min(limit, 500)),
        )
        return {"items": [_serialize_chapter_candidate(row) for row in rows]}

    @app.post(
        "/v2/projects/{project_id}/chapter-candidates/{candidate_id}/approve",
        tags=["Chapters"],
        summary="审批候选稿通过",
        description="通过后写入正式章节与长期记忆，并恢复 run 继续执行。",
    )
    def approve_chapter_candidate(
        project_id: UUID,
        candidate_id: UUID,
        req: Request,
        db: Session = Depends(get_db),
    ) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(db=db, project_id=project_id, user=user, min_role="editor")
        service = req.app.state.orchestrator_factory(db)
        candidate = ChapterCandidateRepository(db).get(candidate_id)
        if candidate is None or str(candidate.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="candidate 不存在")
        try:
            data = service.approve_candidate(candidate_id, approved_by=UUID(str(user["id"])))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if data is None:
            raise HTTPException(status_code=404, detail="candidate 不存在")
        return {"ok": True, **data}

    @app.post(
        "/v2/projects/{project_id}/chapter-candidates/{candidate_id}/reject",
        tags=["Chapters"],
        summary="拒绝候选稿",
        description="拒绝后可选择取消 run 或继续等待审稿。",
    )
    def reject_chapter_candidate(
        project_id: UUID,
        candidate_id: UUID,
        payload: ChapterCandidateRejectPayload,
        req: Request,
        db: Session = Depends(get_db),
    ) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(db=db, project_id=project_id, user=user, min_role="editor")
        service = req.app.state.orchestrator_factory(db)
        candidate = ChapterCandidateRepository(db).get(candidate_id)
        if candidate is None or str(candidate.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="candidate 不存在")
        try:
            data = service.reject_candidate(
                candidate_id,
                rejected_by=UUID(str(user["id"])),
                cancel_run=bool(payload.cancel_run),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if data is None:
            raise HTTPException(status_code=404, detail="candidate 不存在")
        return {"ok": True, **data}

    @app.post(
        "/v2/projects/{project_id}/webhooks",
        tags=["Projects"],
        summary="创建 webhook 订阅",
        description="owner 可创建 webhook 回调订阅。",
    )
    def create_webhook_subscription(
        project_id: UUID,
        payload: WebhookSubscriptionCreatePayload,
        req: Request,
        db: Session = Depends(get_db),
    ) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(db=db, project_id=project_id, user=user, min_role="owner")
        row = WebhookSubscriptionRepository(db).create(
            project_id=project_id,
            event_type=payload.event_type,
            target_url=payload.target_url,
            secret=payload.secret,
            created_by=UUID(str(user["id"])),
            max_retries=payload.max_retries,
            timeout_seconds=payload.timeout_seconds,
            headers_json=payload.headers_json,
            metadata_json=payload.metadata_json,
        )
        return _serialize_webhook_subscription(row)

    @app.get(
        "/v2/projects/{project_id}/webhooks",
        tags=["Projects"],
        summary="查询 webhook 订阅",
        description="查看项目 webhook 订阅列表。",
    )
    def list_webhook_subscriptions(project_id: UUID, req: Request, db: Session = Depends(get_db)) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(db=db, project_id=project_id, user=user, min_role="viewer")
        rows = WebhookSubscriptionRepository(db).list_by_project(project_id=project_id, include_paused=True)
        return {"items": [_serialize_webhook_subscription(row) for row in rows]}

    @app.patch(
        "/v2/projects/{project_id}/webhooks/{subscription_id}",
        tags=["Projects"],
        summary="更新 webhook 订阅",
        description="owner 可暂停/恢复 webhook 订阅。",
    )
    def update_webhook_subscription(
        project_id: UUID,
        subscription_id: UUID,
        payload: WebhookSubscriptionUpdatePayload,
        req: Request,
        db: Session = Depends(get_db),
    ) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(db=db, project_id=project_id, user=user, min_role="owner")
        repo = WebhookSubscriptionRepository(db)
        row = repo.get(subscription_id)
        if row is None or str(row.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="subscription 不存在")
        updated = repo.update(
            subscription_id,
            status=payload.status,
            max_retries=payload.max_retries,
            timeout_seconds=payload.timeout_seconds,
            headers_json=payload.headers_json,
            metadata_json=payload.metadata_json,
        )
        return _serialize_webhook_subscription(updated)

    @app.delete(
        "/v2/projects/{project_id}/webhooks/{subscription_id}",
        tags=["Projects"],
        summary="删除 webhook 订阅",
        description="owner 可删除 webhook 订阅。",
    )
    def delete_webhook_subscription(
        project_id: UUID,
        subscription_id: UUID,
        req: Request,
        db: Session = Depends(get_db),
    ) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(db=db, project_id=project_id, user=user, min_role="owner")
        repo = WebhookSubscriptionRepository(db)
        row = repo.get(subscription_id)
        if row is None or str(row.project_id) != str(project_id):
            raise HTTPException(status_code=404, detail="subscription 不存在")
        repo.delete(subscription_id)
        return {"ok": True, "id": str(subscription_id)}

    @app.get(
        "/v2/projects/{project_id}/webhooks/deliveries",
        tags=["Projects"],
        summary="查询 webhook 投递记录",
        description="查看项目 webhook delivery 状态与重试情况。",
    )
    def list_webhook_deliveries(
        project_id: UUID,
        req: Request,
        limit: int = 200,
        db: Session = Depends(get_db),
    ) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(db=db, project_id=project_id, user=user, min_role="viewer")
        rows = WebhookDeliveryRepository(db).list_by_project(project_id=project_id, limit=max(1, min(limit, 500)))
        return {"items": [_serialize_webhook_delivery(row) for row in rows]}

    def _collect_system_metrics(req: Request, db: Session) -> dict[str, Any]:
        counters, histograms = req.app.state.metrics_registry.snapshot()

        run_repo = WorkflowRunRepository(db)
        recent_runs = run_repo.list_recent(limit=500)
        status_counter: dict[str, int] = {}
        for item in recent_runs:
            key = str(item.status)
            status_counter[key] = status_counter.get(key, 0) + 1

        queue_depth = int(
            db.execute(
                sa.text("select count(*) from workflow_runs where status in ('queued','running','waiting_review')")
            ).scalar()
            or 0
        )
        run_success = int(
            db.execute(sa.text("select count(*) from workflow_runs where status = 'success'")).scalar() or 0
        )
        run_failed = int(
            db.execute(sa.text("select count(*) from workflow_runs where status = 'failed'")).scalar() or 0
        )
        step_failed = int(
            db.execute(sa.text("select count(*) from workflow_steps where status = 'failed'")).scalar() or 0
        )

        retrieval_rounds = int(db.execute(sa.text("select count(*) from retrieval_rounds")).scalar() or 0)
        retrieval_cov = float(
            db.execute(sa.text("select coalesce(avg(coverage_score), 0) from retrieval_rounds")).scalar() or 0.0
        )

        llm_calls = int(
            db.execute(
                sa.text("select count(*) from tool_calls where tool_name like 'llm_%' and status = 'success'")
            ).scalar()
            or 0
        )
        llm_fail = int(
            db.execute(
                sa.text("select count(*) from tool_calls where tool_name like 'llm_%' and status = 'failed'")
            ).scalar()
            or 0
        )

        skills_executed = int(
            db.execute(sa.text("select count(*) from skill_runs where status = 'success'")).scalar() or 0
        )
        skills_effective_delta = int(
            db.execute(
                sa.text(
                    """
                    select coalesce(
                      sum(
                        case
                          when (output_snapshot_json->>'effective_delta') ~ '^-?[0-9]+$'
                          then (output_snapshot_json->>'effective_delta')::bigint
                          else 0
                        end
                      ),
                      0
                    )
                    from skill_runs
                    where status = 'success'
                    """
                )
            ).scalar()
            or 0
        )
        skills_fallback_used = int(
            db.execute(
                sa.text(
                    """
                    select count(*)
                    from skill_runs
                    where status = 'success'
                      and coalesce(output_snapshot_json->>'fallback_used', 'false') = 'true'
                    """
                )
            ).scalar()
            or 0
        )
        skills_no_effect = int(
            db.execute(
                sa.text(
                    """
                    select count(*)
                    from skill_runs
                    where status = 'success'
                      and coalesce(output_snapshot_json->>'no_effect_reason', '') <> ''
                    """
                )
            ).scalar()
            or 0
        )
        mode_rows = db.execute(
            sa.text(
                """
                select coalesce(output_snapshot_json->>'execution_mode', 'unknown') as execution_mode, count(*) as c
                from skill_runs
                group by 1
                """
            )
        ).all()
        mode_coverage = {
            str(execution_mode or "unknown").strip() or "unknown": int(count or 0)
            for execution_mode, count in mode_rows
        }

        findings_count = 0
        evidence_count = 0
        metric_rows_count = 0
        external_evidence_count = 0
        try:
            findings_count = int(db.execute(sa.text("select count(*) from skill_findings")).scalar() or 0)
            evidence_count = int(db.execute(sa.text("select count(*) from skill_evidence")).scalar() or 0)
            metric_rows_count = int(db.execute(sa.text("select count(*) from skill_metrics")).scalar() or 0)
            external_evidence_count = int(
                db.execute(
                    sa.text("select count(*) from skill_evidence where coalesce(source_scope, '') = 'external'")
                ).scalar()
                or 0
            )
        except Exception:
            findings_count = 0
            evidence_count = 0
            metric_rows_count = 0
            external_evidence_count = 0

        required_covered_rate = 1.0
        dead_required_count = 0
        deprecated_unowned_count = 0
        deprecated_missing_retire_by_count = 0
        invalid_declaration_count = 0
        consumed_by_code = 0
        consumed_by_downstream_prompt = 0
        consumed_by_audit_only = 0
        try:
            orchestrator = req.app.state.orchestrator_factory(db)
            agent_registry = getattr(orchestrator, "agent_registry", None)
            if agent_registry is not None and hasattr(agent_registry, "consumption_coverage_summary"):
                summary = dict(agent_registry.consumption_coverage_summary() or {})
                required_covered_rate = float(summary.get("covered_rate") or 1.0)
                dead_required_count = int(summary.get("dead_required_count") or 0)
                deprecated_unowned_count = int(summary.get("deprecated_unowned_count") or 0)
                deprecated_missing_retire_by_count = int(summary.get("deprecated_missing_retire_by_count") or 0)
                invalid_declaration_count = int(summary.get("invalid_declaration_count") or 0)
                consumed_by = dict(summary.get("consumed_by_breakdown") or {})
                consumed_by_code = int(consumed_by.get("code") or 0)
                consumed_by_downstream_prompt = int(consumed_by.get("downstream_prompt") or 0)
                consumed_by_audit_only = int(consumed_by.get("audit_only") or 0)
        except Exception:
            pass

        webhook_success = int(
            db.execute(sa.text("select count(*) from webhook_deliveries where status = 'success'")).scalar() or 0
        )
        webhook_dead = int(
            db.execute(sa.text("select count(*) from webhook_deliveries where status = 'dead'")).scalar() or 0
        )

        return {
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "windows": {"recent_runs_limit": 500},
            "api_metrics": _serialize_metrics_snapshot(counters, histograms),
            "workflow": {
                "recent_by_status": status_counter,
                "queue_depth": queue_depth,
                "runs_success_total": run_success,
                "runs_failed_total": run_failed,
                "steps_failed_total": step_failed,
            },
            "retrieval": {
                "rounds_total": retrieval_rounds,
                "coverage_avg": retrieval_cov,
            },
            "llm": {
                "calls_success_total": llm_calls,
                "calls_failed_total": llm_fail,
            },
            "skills": {
                "executed_count": skills_executed,
                "effective_delta": skills_effective_delta,
                "fallback_used_count": skills_fallback_used,
                "no_effect_count": skills_no_effect,
                "mode_coverage": mode_coverage,
                "findings_total": findings_count,
                "evidence_total": evidence_count,
                "metrics_rows_total": metric_rows_count,
                "fact_external_evidence_total": external_evidence_count,
            },
            "schema_contract": {
                "required_covered_rate": required_covered_rate,
                "dead_required_count": dead_required_count,
                "deprecated_unowned_count": deprecated_unowned_count,
                "deprecated_missing_retire_by_count": deprecated_missing_retire_by_count,
                "invalid_consumption_declaration_count": invalid_declaration_count,
                "consumed_by_code_count": consumed_by_code,
                "consumed_by_downstream_prompt_count": consumed_by_downstream_prompt,
                "consumed_by_audit_only_count": consumed_by_audit_only,
            },
            "webhooks": {
                "delivery_success_total": webhook_success,
                "delivery_dead_total": webhook_dead,
            },
        }

    @app.get(
        "/v2/system/metrics",
        tags=["System"],
        summary="Prometheus 指标",
        description="内部指标出口，需管理员权限。",
    )
    def system_metrics(req: Request, db: Session = Depends(get_db)) -> PlainTextResponse:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        if not _is_system_admin(user):
            raise HTTPException(status_code=403, detail="需要管理员权限")

        counters, histograms = req.app.state.metrics_registry.snapshot()
        metrics_text = render_prometheus(counters, histograms)

        run_repo = WorkflowRunRepository(db)
        runs = run_repo.list_recent(limit=500)
        status_counter: dict[str, int] = {}
        for item in runs:
            key = str(item.status)
            status_counter[key] = status_counter.get(key, 0) + 1
        for key, value in status_counter.items():
            metrics_text += f'writeragent_workflow_runs_recent_total{{status=\"{key}\"}} {value}\\n'

        queue_depth = int(
            db.execute(
                sa.text(
                    "select count(*) from workflow_runs where status in ('queued','running','waiting_review')"
                )
            ).scalar()
            or 0
        )
        metrics_text += f"writeragent_workflow_queue_depth {queue_depth}\\n"

        run_success = int(
            db.execute(sa.text("select count(*) from workflow_runs where status = 'success'")).scalar() or 0
        )
        run_failed = int(
            db.execute(sa.text("select count(*) from workflow_runs where status = 'failed'")).scalar() or 0
        )
        metrics_text += f"writeragent_workflow_runs_success_total {run_success}\\n"
        metrics_text += f"writeragent_workflow_runs_failed_total {run_failed}\\n"

        step_failed = int(
            db.execute(sa.text("select count(*) from workflow_steps where status = 'failed'")).scalar() or 0
        )
        metrics_text += f"writeragent_workflow_steps_failed_total {step_failed}\\n"

        retrieval_rounds = int(db.execute(sa.text("select count(*) from retrieval_rounds")).scalar() or 0)
        retrieval_cov = float(
            db.execute(sa.text("select coalesce(avg(coverage_score), 0) from retrieval_rounds")).scalar() or 0.0
        )
        metrics_text += f"writeragent_retrieval_rounds_total {retrieval_rounds}\\n"
        metrics_text += f"writeragent_retrieval_coverage_avg {retrieval_cov:.6f}\\n"

        llm_calls = int(
            db.execute(
                sa.text("select count(*) from tool_calls where tool_name like 'llm_%' and status = 'success'")
            ).scalar()
            or 0
        )
        llm_fail = int(
            db.execute(
                sa.text("select count(*) from tool_calls where tool_name like 'llm_%' and status = 'failed'")
            ).scalar()
            or 0
        )
        metrics_text += f"writeragent_llm_calls_success_total {llm_calls}\\n"
        metrics_text += f"writeragent_llm_calls_failed_total {llm_fail}\\n"

        skills_executed = int(
            db.execute(sa.text("select count(*) from skill_runs where status = 'success'")).scalar() or 0
        )
        skills_effective_delta = int(
            db.execute(
                sa.text(
                    """
                    select coalesce(
                      sum(
                        case
                          when (output_snapshot_json->>'effective_delta') ~ '^-?[0-9]+$'
                          then (output_snapshot_json->>'effective_delta')::bigint
                          else 0
                        end
                      ),
                      0
                    )
                    from skill_runs
                    where status = 'success'
                    """
                )
            ).scalar()
            or 0
        )
        skills_fallback_used = int(
            db.execute(
                sa.text(
                    """
                    select count(*)
                    from skill_runs
                    where status = 'success'
                      and coalesce(output_snapshot_json->>'fallback_used', 'false') = 'true'
                    """
                )
            ).scalar()
            or 0
        )
        skills_no_effect = int(
            db.execute(
                sa.text(
                    """
                    select count(*)
                    from skill_runs
                    where status = 'success'
                      and coalesce(output_snapshot_json->>'no_effect_reason', '') <> ''
                    """
                )
            ).scalar()
            or 0
        )
        mode_rows = db.execute(
            sa.text(
                """
                select coalesce(output_snapshot_json->>'execution_mode', 'unknown') as execution_mode, count(*) as c
                from skill_runs
                group by 1
                """
            )
        ).all()
        metrics_text += f"writeragent_skills_executed_count {skills_executed}\\n"
        metrics_text += f"writeragent_skills_effective_delta {skills_effective_delta}\\n"
        metrics_text += f"writeragent_skills_fallback_used_count {skills_fallback_used}\\n"
        metrics_text += f"writeragent_skills_no_effect_count {skills_no_effect}\\n"
        for execution_mode, count in mode_rows:
            mode_key = str(execution_mode or "unknown").replace('"', "").strip() or "unknown"
            metrics_text += f'writeragent_skill_mode_coverage_total{{execution_mode=\"{mode_key}\"}} {int(count or 0)}\\n'

        try:
            findings_count = int(db.execute(sa.text("select count(*) from skill_findings")).scalar() or 0)
            evidence_count = int(db.execute(sa.text("select count(*) from skill_evidence")).scalar() or 0)
            metric_rows_count = int(db.execute(sa.text("select count(*) from skill_metrics")).scalar() or 0)
            external_evidence_count = int(
                db.execute(
                    sa.text(
                        """
                        select count(*) from skill_evidence
                        where coalesce(source_scope, '') = 'external'
                        """
                    )
                ).scalar()
                or 0
            )
            metrics_text += f"writeragent_skill_findings_total {findings_count}\\n"
            metrics_text += f"writeragent_skill_evidence_total {evidence_count}\\n"
            metrics_text += f"writeragent_skill_metrics_rows_total {metric_rows_count}\\n"
            metrics_text += f"writeragent_fact_external_evidence_total {external_evidence_count}\\n"
        except Exception:
            pass

        required_covered_rate = 1.0
        dead_required_count = 0
        deprecated_unowned_count = 0
        deprecated_missing_retire_by_count = 0
        invalid_declaration_count = 0
        consumed_by_code = 0
        consumed_by_downstream_prompt = 0
        consumed_by_audit_only = 0
        try:
            orchestrator = req.app.state.orchestrator_factory(db)
            agent_registry = getattr(orchestrator, "agent_registry", None)
            if agent_registry is not None and hasattr(agent_registry, "consumption_coverage_summary"):
                summary = dict(agent_registry.consumption_coverage_summary() or {})
                required_covered_rate = float(summary.get("covered_rate") or 1.0)
                dead_required_count = int(summary.get("dead_required_count") or 0)
                deprecated_unowned_count = int(summary.get("deprecated_unowned_count") or 0)
                deprecated_missing_retire_by_count = int(summary.get("deprecated_missing_retire_by_count") or 0)
                invalid_declaration_count = int(summary.get("invalid_declaration_count") or 0)
                consumed_by = dict(summary.get("consumed_by_breakdown") or {})
                consumed_by_code = int(consumed_by.get("code") or 0)
                consumed_by_downstream_prompt = int(consumed_by.get("downstream_prompt") or 0)
                consumed_by_audit_only = int(consumed_by.get("audit_only") or 0)
        except Exception:
            pass
        metrics_text += f"writeragent_required_covered_rate {required_covered_rate:.6f}\\n"
        metrics_text += f"writeragent_dead_required_count {dead_required_count}\\n"
        metrics_text += f"writeragent_deprecated_unowned_count {deprecated_unowned_count}\\n"
        metrics_text += (
            f"writeragent_deprecated_missing_retire_by_count {deprecated_missing_retire_by_count}\\n"
        )
        metrics_text += f"writeragent_invalid_consumption_declaration_count {invalid_declaration_count}\\n"
        metrics_text += f"writeragent_consumed_by_code_count {consumed_by_code}\\n"
        metrics_text += f"writeragent_consumed_by_downstream_prompt_count {consumed_by_downstream_prompt}\\n"
        metrics_text += f"writeragent_consumed_by_audit_only_count {consumed_by_audit_only}\\n"

        webhook_success = int(
            db.execute(sa.text("select count(*) from webhook_deliveries where status = 'success'")).scalar() or 0
        )
        webhook_dead = int(
            db.execute(sa.text("select count(*) from webhook_deliveries where status = 'dead'")).scalar() or 0
        )
        metrics_text += f"writeragent_webhook_delivery_success_total {webhook_success}\\n"
        metrics_text += f"writeragent_webhook_delivery_dead_total {webhook_dead}\\n"

        return PlainTextResponse(metrics_text, media_type="text/plain; version=0.0.4")

    @app.get(
        "/v2/system/metrics/json",
        tags=["System"],
        summary="结构化系统指标",
        description="结构化 JSON 指标出口，供前端控制台直接消费。",
    )
    def system_metrics_json(req: Request, db: Session = Depends(get_db)) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        if not _is_system_admin(user):
            raise HTTPException(status_code=403, detail="需要管理员权限")
        return _collect_system_metrics(req, db)

    @app.get(
        "/v2/system/backups/latest",
        tags=["System"],
        summary="最近一次备份",
        description="返回最近一次 backup run。",
    )
    def latest_backup(req: Request, db: Session = Depends(get_db)) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        if not _is_system_admin(user):
            raise HTTPException(status_code=403, detail="需要管理员权限")
        row = BackupRunRepository(db).latest()
        if row is None:
            raise HTTPException(status_code=404, detail="暂无备份记录")
        return _serialize_backup_run(row)

    @app.post(
        "/v2/system/backups/full",
        tags=["System"],
        summary="触发全量备份",
        description="执行 pg_dump 并写入 backup_runs。",
    )
    def trigger_full_backup(
        req: Request,
        output_dir: str = "data/backups",
        db: Session = Depends(get_db),
    ) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        if not _is_system_admin(user):
            raise HTTPException(status_code=403, detail="需要管理员权限")
        try:
            result = BackupService(repo=BackupRunRepository(db)).run_full_backup(output_dir=output_dir)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        AuditService(repo=AuditEventRepository(db)).log(
            action="backup_full",
            resource_type="system",
            resource_id=None,
            user_id=UUID(str(user["id"])),
            payload_json=result,
        )
        return {"ok": True, **result}

    @app.get(
        "/v2/system/backups/runs",
        tags=["System"],
        summary="备份记录列表",
        description="返回 backup run 列表。",
    )
    def list_backup_runs(req: Request, limit: int = 50, db: Session = Depends(get_db)) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        if not _is_system_admin(user):
            raise HTTPException(status_code=403, detail="需要管理员权限")
        rows = BackupRunRepository(db).list_runs(limit=max(1, min(limit, 500)))
        return {"items": [_serialize_backup_run(row) for row in rows]}

    @app.post(
        "/v2/projects/{project_id}/exports",
        tags=["Projects"],
        summary="创建导出任务",
        description="导出项目快照包（默认不含长期记忆向量）。",
    )
    def export_project(
        project_id: UUID,
        payload: ProjectExportPayload,
        req: Request,
        db: Session = Depends(get_db),
    ) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        ensure_project_role(db=db, project_id=project_id, user=user, min_role="editor")
        transfer = ProjectTransferService(db=db, repo=ProjectTransferJobRepository(db))
        try:
            result = transfer.export_project(
                project_id=project_id,
                created_by=UUID(str(user["id"])),
                output_dir=payload.output_dir,
                include_chapters=payload.include_chapters,
                include_versions=payload.include_versions,
                include_long_term_memory=payload.include_long_term_memory,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        AuditService(repo=AuditEventRepository(db)).log(
            action="project_export",
            resource_type="project",
            resource_id=str(project_id),
            project_id=project_id,
            user_id=UUID(str(user["id"])),
            payload_json=result,
        )
        return {"ok": True, **result}

    @app.get(
        "/v2/exports/{job_id}",
        tags=["Projects"],
        summary="查询导出任务",
        description="按 job_id 查询导出/导入任务状态。",
    )
    def get_export_job(job_id: UUID, req: Request, db: Session = Depends(get_db)) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        row = ProjectTransferJobRepository(db).get(job_id)
        if row is None:
            raise HTTPException(status_code=404, detail="job 不存在")
        if row.project_id is not None:
            ensure_project_role(db=db, project_id=row.project_id, user=user, min_role="viewer")
        elif not _is_system_admin(user):
            raise HTTPException(status_code=403, detail="仅管理员可查看跨项目导入任务")
        return _serialize_transfer_job(row)

    @app.post(
        "/v2/projects/imports",
        tags=["Projects"],
        summary="创建导入任务",
        description="从快照包导入项目。",
    )
    def import_project(payload: ProjectImportPayload, req: Request, db: Session = Depends(get_db)) -> dict:
        user = getattr(req.state, "current_user", None) or current_user(req, db)
        transfer = ProjectTransferService(db=db, repo=ProjectTransferJobRepository(db))
        try:
            result = transfer.import_project(
                source_path=payload.source_path,
                created_by=UUID(str(user["id"])),
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        imported_project_id = result.get("project_id")
        if imported_project_id:
            ProjectMembershipRepository(db).create_or_update(
                project_id=UUID(str(imported_project_id)),
                user_id=UUID(str(user["id"])),
                role="owner",
                status="active",
            )
        AuditService(repo=AuditEventRepository(db)).log(
            action="project_import",
            resource_type="project",
            resource_id=str(imported_project_id) if imported_project_id else None,
            project_id=UUID(str(imported_project_id)) if imported_project_id else None,
            user_id=UUID(str(user["id"])),
            payload_json=result,
        )
        return {"ok": True, **result}

    return app


app = create_app()
