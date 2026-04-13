from __future__ import annotations

import json
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, TYPE_CHECKING

from packages.core.tracing import new_request_id, new_trace_id, request_context
from packages.core.utils import ensure_non_empty_string
from packages.llm.text_generation.base import TextGenerationProvider, TextGenerationRequest
from packages.memory.long_term.ingestion.ingestion_service import MemoryIngestionService
from packages.memory.project_memory.project_memory_service import ProjectMemoryService
from packages.schemas import SchemaRegistry
from packages.skills import SkillRuntimeContext, SkillRuntimeEngine
from packages.skills.registry import SkillSpec
from packages.storage.postgres.repositories.agent_run_repository import AgentRunRepository
from packages.storage.postgres.repositories.chapter_repository import ChapterRepository
from packages.storage.postgres.repositories.project_repository import ProjectRepository
from packages.storage.postgres.repositories.skill_run_repository import SkillRunRepository
from packages.storage.postgres.repositories.tool_call_repository import ToolCallRepository
from packages.workflows.chapter_generation.context_provider import (
    SQLAlchemyStoryContextProvider,
)
from packages.workflows.chapter_generation.types import (
    ChapterGenerationRequest,
    ChapterGenerationResult,
)
from packages.workflows.writer_output import WriterOutputAdapter

if TYPE_CHECKING:
    from packages.workflows.orchestration.agent_registry import AgentRegistry


class ChapterGenerationWorkflowError(RuntimeError):
    """章节生成 workflow 运行异常。"""


class ChapterGenerationWorkflowService:
    AGENT_NAME = "chapter_writer_agent"
    WORKFLOW_NAME = "chapter_generation"
    CHAPTER_INPUT_SCHEMA = {
        "type": "object",
        "required": [
            "project",
            "goal",
            "target_words",
            "memory_context",
            "story_constraints",
            "output_format",
        ],
        "properties": {
            "project": {"type": "object"},
            "goal": {"type": "string", "minLength": 1},
            "target_words": {"type": "integer", "minimum": 100},
            "style_hint": {"type": ["string", "null"]},
            "memory_context": {"type": "array"},
            "story_constraints": {"type": "object"},
            "working_notes": {
                "type": "array",
                "items": {"type": "string"},
            },
            "retrieval_context": {"type": ["string", "null"]},
            "output_format": {"type": "object"},
        },
        "additionalProperties": True,
    }
    # 兼容旧链路；当启用 writer_agent registry 时会使用 writer_agent/output_schema.json。
    CHAPTER_OUTPUT_SCHEMA = {
        "type": "object",
        "required": ["title", "content", "summary"],
        "properties": {
            "title": {"type": "string", "minLength": 1},
            "content": {"type": "string", "minLength": 1},
            "summary": {"type": "string", "minLength": 1},
        },
        "additionalProperties": True,
    }

    def __init__(
        self,
        *,
        project_repo: ProjectRepository,
        chapter_repo: ChapterRepository,
        agent_run_repo: AgentRunRepository,
        tool_call_repo: ToolCallRepository,
        skill_run_repo: SkillRunRepository,
        story_context_provider: SQLAlchemyStoryContextProvider,
        project_memory_service: ProjectMemoryService,
        ingestion_service: MemoryIngestionService,
        text_provider: TextGenerationProvider,
        default_context_token_budget: int = 3200,
        agent_registry: AgentRegistry | None = None,
        schema_registry: SchemaRegistry | None = None,
        skill_runtime: SkillRuntimeEngine | None = None,
    ) -> None:
        self.project_repo = project_repo
        self.chapter_repo = chapter_repo
        self.agent_run_repo = agent_run_repo
        self.tool_call_repo = tool_call_repo
        self.skill_run_repo = skill_run_repo
        self.story_context_provider = story_context_provider
        self.project_memory_service = project_memory_service
        self.ingestion_service = ingestion_service
        self.text_provider = text_provider
        self.default_context_token_budget = max(400, int(default_context_token_budget))
        self.agent_registry = agent_registry
        self.schema_registry = schema_registry
        self.skill_runtime = skill_runtime or SkillRuntimeEngine()

    def run(self, request: ChapterGenerationRequest) -> ChapterGenerationResult:
        started_at = perf_counter()
        writing_goal = ensure_non_empty_string(
            request.writing_goal,
            field_name="writing_goal",
        )
        request_id = request.request_id or new_request_id()
        trace_id = request.trace_id or new_trace_id()

        with request_context(request_id=request_id, trace_id=trace_id):
            run_row = self.agent_run_repo.create_run(
                trace_id=trace_id,
                request_id=request_id,
                project_id=request.project_id,
                agent_name=self.AGENT_NAME,
                task_type=self.WORKFLOW_NAME,
                input_json={
                    "writing_goal": writing_goal,
                    "chapter_no": request.chapter_no,
                    "target_words": request.target_words,
                    "style_hint": request.style_hint,
                    "include_memory_top_k": request.include_memory_top_k,
                    "context_token_budget": request.context_token_budget,
                    "temperature": request.temperature,
                },
            )
            self.agent_run_repo.start(run_row.id)

            chapter_row = None
            version_row = None
            created_new_chapter = False
            chapter_snapshot: dict[str, Any] | None = None
            active_tool_call_id = None
            active_skill_run_ids: list[Any] = []

            try:
                project = self.project_repo.get(request.project_id)
                if project is None:
                    raise ChapterGenerationWorkflowError("project 不存在")

                retrieval_call = self.tool_call_repo.create_call(
                    trace_id=trace_id,
                    agent_run_id=run_row.id,
                    tool_name="project_memory_retrieval",
                    input_json={
                        "project_id": str(request.project_id),
                        "query": writing_goal,
                        "top_k": int(request.include_memory_top_k),
                        "context_token_budget": int(
                            request.context_token_budget or self.default_context_token_budget
                        ),
                    },
                )
                self.tool_call_repo.start(retrieval_call.id)
                active_tool_call_id = retrieval_call.id

                memory_context = self.project_memory_service.build_context(
                    project_id=request.project_id,
                    query=writing_goal,
                    token_budget=max(
                        400,
                        int(request.context_token_budget or self.default_context_token_budget),
                    ),
                    top_k=max(1, int(request.include_memory_top_k)),
                    chat_turns=request.chat_turns,
                    working_notes=request.working_notes,
                )
                story_context = self.story_context_provider.load(
                    project_id=request.project_id,
                    chapter_no=request.chapter_no,
                )
                self.tool_call_repo.succeed(
                    retrieval_call.id,
                    output_json={
                        "memory_items": len(memory_context.items),
                        "chapters": len(story_context.chapters),
                        "characters": len(story_context.characters),
                        "world_entries": len(story_context.world_entries),
                        "timeline_events": len(story_context.timeline_events),
                        "foreshadowings": len(story_context.foreshadowings),
                    },
                )
                active_tool_call_id = None

                runtime = self._resolve_writer_runtime(
                    workflow_type=self.WORKFLOW_NAME,
                    step_key="writer_draft",
                    strategy_mode="draft",
                )
                runtime_warnings = [
                    str(item)
                    for item in list(runtime.get("warnings") or [])
                    if str(item).strip()
                ]
                skill_specs = list(runtime.get("skills") or [])
                if not skill_specs:
                    skill_specs = [
                        SkillSpec(
                            id="chapter_writing",
                            name="chapter_writing",
                            version="v1",
                            description="fallback chapter writing skill",
                            tags=["fallback"],
                        )
                    ]

                llm_call = self.tool_call_repo.create_call(
                    trace_id=trace_id,
                    agent_run_id=run_row.id,
                    tool_name="llm_generate_chapter",
                    input_json={
                        "target_words": int(request.target_words),
                        "temperature": float(request.temperature),
                        "style_hint": request.style_hint,
                        "strategy_version": runtime.get("strategy_version"),
                        "schema_ref": runtime.get("schema_ref"),
                    },
                )
                self.tool_call_repo.start(llm_call.id)
                active_tool_call_id = llm_call.id

                for spec in skill_specs:
                    skill_run = self.skill_run_repo.create_run(
                        trace_id=trace_id,
                        agent_run_id=run_row.id,
                        skill_name=spec.id,
                        skill_version=spec.version,
                        role_id="writer_agent",
                        strategy_version=str(runtime.get("strategy_version") or "v1"),
                        schema_version=str(runtime.get("schema_version") or "v1"),
                        input_snapshot_json={
                            "temperature": request.temperature,
                            "target_words": request.target_words,
                            "workflow": self.WORKFLOW_NAME,
                        },
                    )
                    self.skill_run_repo.start(skill_run.id)
                    active_skill_run_ids.append(skill_run.id)

                system_prompt = str(runtime.get("system_prompt") or self._legacy_system_prompt())
                prompt_payload = self._build_user_prompt(
                    project=project,
                    writing_goal=writing_goal,
                    target_words=request.target_words,
                    style_hint=request.style_hint,
                    memory_context=memory_context,
                    story_context=story_context,
                    working_notes=request.working_notes,
                    retrieval_context=request.retrieval_context,
                )
                if runtime.get("using_writer_schema"):
                    prompt_payload["output_format"] = {
                        "schema_ref": "apps/agents/writer_agent/output_schema.json",
                        "contract": "WriterOutputV2",
                    }

                before = self.skill_runtime.run_before_generate(
                    skills=skill_specs,
                    system_prompt=system_prompt,
                    input_payload=prompt_payload,
                    context=SkillRuntimeContext(
                        trace_id=trace_id,
                        role_id="writer_agent",
                        workflow_type=self.WORKFLOW_NAME,
                        step_key="writer_draft",
                        mode="draft",
                    ),
                )
                user_prompt = json.dumps(before.input_payload, ensure_ascii=False)

                runtime_temp = (
                    float(runtime.get("temperature") or request.temperature)
                    if runtime.get("using_writer_schema")
                    else float(request.temperature)
                )
                runtime_max_tokens = (
                    int(runtime.get("max_tokens"))
                    if runtime.get("using_writer_schema") and runtime.get("max_tokens") is not None
                    else None
                )
                llm_output = self.text_provider.generate(
                    TextGenerationRequest(
                        system_prompt=before.system_prompt,
                        user_prompt=user_prompt,
                        temperature=runtime_temp,
                        max_tokens=runtime_max_tokens,
                        input_payload=before.input_payload,
                        input_schema=self.CHAPTER_INPUT_SCHEMA,
                        input_schema_name="chapter_generation_input",
                        input_schema_strict=True,
                        response_schema=runtime.get("response_schema") or self.CHAPTER_OUTPUT_SCHEMA,
                        response_schema_name="chapter_generation_output",
                        response_schema_strict=True,
                        validation_retries=2,
                        use_function_calling=True,
                        function_name="chapter_generation_output",
                        function_description="Return chapter writer output as JSON.",
                        metadata_json={
                            "target_words": request.target_words,
                            "workflow": self.WORKFLOW_NAME,
                            "trace_id": trace_id,
                            "strategy_version": runtime.get("strategy_version"),
                            "schema_ref": runtime.get("schema_ref"),
                        },
                    )
                )

                after = self.skill_runtime.run_after_generate(
                    skills=skill_specs,
                    output_payload=dict(llm_output.json_data or {}),
                    context=SkillRuntimeContext(
                        trace_id=trace_id,
                        role_id="writer_agent",
                        workflow_type=self.WORKFLOW_NAME,
                        step_key="writer_draft",
                        mode="draft",
                    ),
                )

                writer_structured = WriterOutputAdapter.normalize(
                    dict(after.output_payload or {}),
                    mode="draft",
                )
                legacy = WriterOutputAdapter.legacy_chapter(writer_structured)
                draft_title = str(legacy.get("title") or "").strip() or "未命名章节"
                draft_content = str(legacy.get("content") or "").strip()
                draft_summary = str(legacy.get("summary") or "").strip()
                if not draft_content:
                    raise ChapterGenerationWorkflowError("LLM 输出缺少 content")

                skill_runs_payload = self._build_skill_runs_payload(
                    skills=skill_specs,
                    before_runs=list(before.runs or []),
                    after_runs=list(after.runs or []),
                )
                for run_id, snapshot in zip(active_skill_run_ids, skill_runs_payload):
                    self.skill_run_repo.succeed(run_id, output_snapshot_json=snapshot)
                active_skill_run_ids = []

                all_warnings = []
                all_warnings.extend(runtime_warnings)
                all_warnings.extend([str(item) for item in list(before.warnings or []) if str(item).strip()])
                all_warnings.extend([str(item) for item in list(after.warnings or []) if str(item).strip()])

                self.tool_call_repo.succeed(
                    llm_call.id,
                    output_json={
                        "provider": llm_output.provider,
                        "model": llm_output.model,
                        "is_mock": llm_output.is_mock,
                        "skills_effective_delta": int(
                            sum(int(item.get("effective_delta") or 0) for item in skill_runs_payload)
                        ),
                    },
                )
                active_tool_call_id = None

                effective_chapter_no = (
                    int(request.chapter_no)
                    if request.chapter_no is not None
                    else int(self.chapter_repo.get_next_chapter_no(request.project_id))
                )

                if not bool(request.persist_chapter):
                    latency_ms = int((perf_counter() - started_at) * 1000)
                    payload = {
                        "trace_id": trace_id,
                        "chapter_no": effective_chapter_no,
                        "mock_mode": bool(llm_output.is_mock),
                        "persist_chapter": False,
                        "warnings": all_warnings,
                    }
                    self.agent_run_repo.succeed(
                        run_row.id,
                        output_json=payload,
                        latency_ms=latency_ms,
                    )
                    return ChapterGenerationResult(
                        trace_id=trace_id,
                        request_id=request_id,
                        agent_run_id=str(run_row.id),
                        mock_mode=bool(llm_output.is_mock),
                        chapter={
                            "id": None,
                            "chapter_no": effective_chapter_no,
                            "title": draft_title,
                            "summary": draft_summary,
                            "content": draft_content,
                            "draft_version": None,
                            "version_id": None,
                        },
                        memory_ingestion={
                            "created_chunks": 0,
                            "persisted": False,
                        },
                        writer_structured=writer_structured,
                        warnings=all_warnings,
                        skill_runs=skill_runs_payload,
                    )

                write_call = self.tool_call_repo.create_call(
                    trace_id=trace_id,
                    agent_run_id=run_row.id,
                    tool_name="chapter_persistence",
                    input_json={
                        "chapter_no": request.chapter_no,
                        "title": draft_title,
                    },
                )
                self.tool_call_repo.start(write_call.id)
                active_tool_call_id = write_call.id

                if request.chapter_no is not None:
                    existing = self.chapter_repo.get_by_project_chapter_no(
                        request.project_id,
                        int(request.chapter_no),
                    )
                    if existing is not None:
                        chapter_snapshot = {
                            "id": existing.id,
                            "title": existing.title,
                            "content": existing.content,
                            "summary": existing.summary,
                            "draft_version": int(existing.draft_version or 1),
                        }

                chapter_row, version_row, created_new_chapter = self.chapter_repo.save_generated_draft(
                    project_id=request.project_id,
                    chapter_no=request.chapter_no,
                    title=draft_title,
                    content=draft_content,
                    summary=draft_summary,
                    source_agent=self.AGENT_NAME,
                    source_workflow=self.WORKFLOW_NAME,
                    trace_id=trace_id,
                )
                self.tool_call_repo.succeed(
                    write_call.id,
                    output_json={
                        "chapter_id": str(chapter_row.id),
                        "chapter_no": int(chapter_row.chapter_no),
                        "version_id": int(version_row.id),
                        "draft_version": int(chapter_row.draft_version),
                    },
                )
                active_tool_call_id = None

                memory_call = self.tool_call_repo.create_call(
                    trace_id=trace_id,
                    agent_run_id=run_row.id,
                    tool_name="memory_ingestion",
                    input_json={
                        "source_type": "chapter",
                        "source_id": str(chapter_row.id),
                    },
                )
                self.tool_call_repo.start(memory_call.id)
                active_tool_call_id = memory_call.id
                ingestion_rows = self.ingestion_service.ingest_text(
                    project_id=request.project_id,
                    text=draft_content,
                    source_type="chapter",
                    source_id=chapter_row.id,
                    chunk_type="chapter_body",
                    metadata_json={
                        "chapter_no": int(chapter_row.chapter_no),
                        "trace_id": trace_id,
                        "generated_by": self.AGENT_NAME,
                    },
                    source_timestamp=datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
                    replace_existing=True,
                )
                self.tool_call_repo.succeed(
                    memory_call.id,
                    output_json={
                        "created_chunks": len(ingestion_rows),
                    },
                )
                active_tool_call_id = None

                latency_ms = int((perf_counter() - started_at) * 1000)
                payload = {
                    "trace_id": trace_id,
                    "chapter_id": str(chapter_row.id),
                    "version_id": int(version_row.id),
                    "mock_mode": bool(llm_output.is_mock),
                    "warnings": all_warnings,
                }
                self.agent_run_repo.succeed(
                    run_row.id,
                    output_json=payload,
                    latency_ms=latency_ms,
                )
                return ChapterGenerationResult(
                    trace_id=trace_id,
                    request_id=request_id,
                    agent_run_id=str(run_row.id),
                    mock_mode=bool(llm_output.is_mock),
                    chapter={
                        "id": str(chapter_row.id),
                        "chapter_no": int(chapter_row.chapter_no),
                        "title": chapter_row.title,
                        "summary": chapter_row.summary,
                        "content": chapter_row.content,
                        "draft_version": int(chapter_row.draft_version),
                        "version_id": int(version_row.id),
                    },
                    memory_ingestion={
                        "created_chunks": len(ingestion_rows),
                    },
                    writer_structured=writer_structured,
                    warnings=all_warnings,
                    skill_runs=skill_runs_payload,
                )
            except Exception as exc:
                if active_tool_call_id is not None:
                    try:
                        self.tool_call_repo.fail(
                            active_tool_call_id,
                            error_code=type(exc).__name__,
                            output_json={"error": str(exc)},
                        )
                    except Exception:
                        pass
                for skill_run_id in list(active_skill_run_ids):
                    try:
                        self.skill_run_repo.fail(
                            skill_run_id,
                            output_snapshot_json={"error": str(exc)},
                        )
                    except Exception:
                        pass
                self._compensate_if_needed(
                    chapter_row=chapter_row,
                    version_row=version_row,
                    created_new_chapter=created_new_chapter,
                    chapter_snapshot=chapter_snapshot,
                )
                latency_ms = int((perf_counter() - started_at) * 1000)
                self.agent_run_repo.fail(
                    run_row.id,
                    error_code=type(exc).__name__,
                    output_json={"error": str(exc)},
                    latency_ms=latency_ms,
                )
                raise

    def _resolve_writer_runtime(
        self,
        *,
        workflow_type: str,
        step_key: str,
        strategy_mode: str,
    ) -> dict[str, Any]:
        default = {
            "system_prompt": self._legacy_system_prompt(),
            "response_schema": dict(self.CHAPTER_OUTPUT_SCHEMA),
            "temperature": 0.65,
            "max_tokens": 2600,
            "skills": [],
            "warnings": [],
            "schema_ref": "inline://chapter_generation/legacy_output",
            "schema_version": "v1",
            "strategy_version": "legacy-v1",
            "using_writer_schema": False,
        }
        if self.agent_registry is None:
            return default

        try:
            profile, strategy, skills, warnings = self.agent_registry.resolve(
                role_id="writer_agent",
                workflow_type=workflow_type,
                step_key=step_key,
                strategy_mode=strategy_mode,
            )
        except Exception as exc:
            default["warnings"] = [f"writer_agent 配置解析失败，回退 legacy schema: {exc}"]
            return default

        schema_payload: dict[str, Any] | None = None
        if isinstance(profile.output_schema, dict) and profile.output_schema:
            schema_payload = dict(profile.output_schema)
        elif self.schema_registry is not None:
            loaded = self.schema_registry.get(profile.schema_ref)
            if isinstance(loaded, dict):
                schema_payload = dict(loaded)

        if not isinstance(schema_payload, dict) or not schema_payload:
            schema_payload = dict(self.CHAPTER_OUTPUT_SCHEMA)

        return {
            "system_prompt": profile.prompt or self._legacy_system_prompt(),
            "response_schema": schema_payload,
            "temperature": float(strategy.temperature),
            "max_tokens": int(strategy.max_tokens),
            "skills": list(skills or []),
            "warnings": [str(item) for item in list(warnings or []) if str(item).strip()],
            "schema_ref": profile.schema_ref,
            "schema_version": profile.schema_version,
            "strategy_version": strategy.version,
            "using_writer_schema": bool(profile.output_schema),
        }

    @staticmethod
    def _build_skill_runs_payload(
        *,
        skills: list[SkillSpec],
        before_runs: list[Any],
        after_runs: list[Any],
    ) -> list[dict[str, Any]]:
        all_runs = list(before_runs) + list(after_runs)
        payloads: list[dict[str, Any]] = []
        for spec in list(skills or []):
            runs = [item for item in all_runs if str(getattr(item, "skill_id", "")) == spec.id]
            statuses = [str(getattr(item, "status", "") or "").strip().lower() for item in runs]
            if any(status == "failed" for status in statuses):
                status = "failed"
            elif all(status == "skipped" for status in statuses) and statuses:
                status = "skipped"
            else:
                status = "success"
            execution_mode = next(
                (
                    str(getattr(item, "execution_mode", "")).strip()
                    for item in runs
                    if str(getattr(item, "execution_mode", "")).strip()
                ),
                str(getattr(spec, "execution_mode_default", "") or "shadow"),
            )
            mode_used = next(
                (
                    str(getattr(item, "mode_used", "")).strip()
                    for item in runs
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
                    "fallback_used": any(bool(getattr(item, "fallback_used", False)) for item in runs),
                    "fallback_reason": next(
                        (
                            str(getattr(item, "fallback_reason", "")).strip()
                            for item in runs
                            if str(getattr(item, "fallback_reason", "")).strip()
                        ),
                        None,
                    ),
                    "status": status,
                    "effective_delta": int(sum(int(getattr(item, "effective_delta", 0) or 0) for item in runs)),
                    "warnings": [
                        str(w)
                        for item in runs
                        for w in list(getattr(item, "warnings", []) or [])
                        if str(w).strip()
                    ],
                    "findings": [
                        dict(v)
                        for item in runs
                        for v in list(getattr(item, "findings", []) or [])
                        if isinstance(v, dict)
                    ],
                    "evidence": [
                        dict(v)
                        for item in runs
                        for v in list(getattr(item, "evidence", []) or [])
                        if isinstance(v, dict)
                    ],
                    "changed_spans": [
                        dict(v)
                        for item in runs
                        for v in list(getattr(item, "changed_spans", []) or [])
                        if isinstance(v, dict)
                    ],
                    "metrics": {
                        key: value
                        for item in runs
                        for key, value in dict(getattr(item, "metrics", {}) or {}).items()
                    },
                    "no_effect_reason": next(
                        (
                            str(getattr(item, "no_effect_reason", "")).strip()
                            for item in runs
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
                        for item in runs
                    ],
                }
            )
        return payloads

    @staticmethod
    def _legacy_system_prompt() -> str:
        return (
            "你是长篇小说写作助手。"
            "请严格输出 JSON 对象，字段仅允许 title/content/summary。"
            "content 必须是完整章节正文。"
        )

    def _build_user_prompt(
        self,
        *,
        project,
        writing_goal: str,
        target_words: int,
        style_hint: str | None,
        memory_context,
        story_context,
        working_notes: list[str] | None = None,
        retrieval_context: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "project": {
                "id": str(project.id),
                "title": project.title,
                "genre": project.genre,
                "premise": project.premise,
                "metadata_json": project.metadata_json or {},
            },
            "goal": writing_goal,
            "target_words": int(target_words),
            "style_hint": style_hint,
            "memory_context": [
                {"source": item.source, "text": item.text, "priority": item.priority}
                for item in memory_context.items
            ],
            "story_constraints": {
                "chapters": story_context.chapters,
                "characters": story_context.characters,
                "world_entries": story_context.world_entries,
                "timeline_events": story_context.timeline_events,
                "foreshadowings": story_context.foreshadowings,
            },
            "working_notes": [
                str(item).strip()
                for item in list(working_notes or [])
                if str(item).strip()
            ],
            "retrieval_context": retrieval_context,
            "output_format": {
                "title": "string",
                "content": "string",
                "summary": "string",
            },
        }
        return payload

    def _compensate_if_needed(
        self,
        *,
        chapter_row,
        version_row,
        created_new_chapter: bool,
        chapter_snapshot: dict[str, Any] | None,
    ) -> None:
        if chapter_row is None:
            return
        try:
            if version_row is not None:
                self.chapter_repo.delete_version(version_row.id, auto_commit=False)
            if created_new_chapter:
                self.chapter_repo.delete(chapter_row.id)
                return

            if chapter_snapshot is None:
                return
            self.chapter_repo.restore_generated_draft(
                chapter_id=chapter_snapshot["id"],
                title=chapter_snapshot["title"],
                content=chapter_snapshot["content"],
                summary=chapter_snapshot["summary"],
                draft_version=chapter_snapshot["draft_version"],
                auto_commit=False,
            )
            self.chapter_repo.db.commit()
        except Exception:
            self.chapter_repo.db.rollback()
