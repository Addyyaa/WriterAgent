from __future__ import annotations

import copy
import json
import logging
import os
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, TYPE_CHECKING

from packages.core.config import env_bool
from packages.core.tracing import new_request_id, new_trace_id, request_context
from packages.core.utils import ensure_non_empty_string
from packages.core.utils.chapter_metrics import (
    chapter_context_token_budget,
    chapter_max_output_tokens,
    chapter_word_count_allowed_range,
    chapter_word_count_violation_message,
    count_fiction_word_units,
)
from packages.llm.text_generation.base import TextGenerationProvider, TextGenerationRequest
from packages.llm.text_generation.schema_errors import ResponseSchemaValidationError
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
from packages.workflows.context_views import (
    build_writer_context_slice,
    build_writer_evidence_pack,
    build_writer_focus,
    build_writer_relevance_blob,
)
from packages.workflows.chapter_generation.types import (
    ChapterGenerationRequest,
    ChapterGenerationResult,
)
from packages.workflows.orchestration.prompt_payload_assembler import (
    PromptPayloadAssembler,
    build_retrieval_bundle_from_raw_state,
)
from packages.workflows.writer_output import (
    WRITER_OUTPUT_CONTRACT_DRAFT,
    WRITER_OUTPUT_CONTRACT_LEGACY_FLAT,
    WRITER_OUTPUT_CONTRACT_V2,
    WRITER_OUTPUT_SCHEMA_REF_DRAFT,
    WRITER_OUTPUT_SCHEMA_REF_LEGACY_INLINE,
    WRITER_OUTPUT_SCHEMA_REF_V2,
    WriterOutputAdapter,
)

if TYPE_CHECKING:
    from packages.workflows.orchestration.agent_registry import AgentRegistry

logger = logging.getLogger(__name__)
# 与 LLM 文件日志同一 logger，便于 tail data/llm.log 对照正文长度
_llm_diag_logger = logging.getLogger("writeragent.llm")


class ChapterGenerationWorkflowError(RuntimeError):
    """章节生成 workflow 运行异常。"""


class ChapterGenerationWorkflowService:
    """章节草稿/扩写工作流。

    主链路 user JSON 由 :meth:`_build_chapter_writer_prompt_payload` 组装：先
    :class:`~packages.workflows.orchestration.prompt_payload_assembler.PromptPayloadAssembler`
    按 ``step_input_specs.STEP_INPUT_SPECS`` 中 ``writer_agent:writer_draft``（编排）或
    ``writer_agent:chapter_draft``（独立 API）做 **投影视图**（含 ``state`` / ``retrieval`` 等），
    再合并 ``goal`` / ``target_words`` / ``writing_contract`` / ``output_format`` 等。
    请求参数 ``retrieval_context`` 只参与构造 ``retrieval_bundle``，**不会**作为顶层字段塞进模型。

    ``consumption.json`` 仅在 :class:`~packages.workflows.orchestration.agent_registry.AgentRegistry`
    侧解析，不进入本 user JSON。``output_format`` 仅含 ``schema_ref`` + ``contract``（
    ``writer.output.v2`` / ``writer.output.draft`` 等，见 ``packages.workflows.writer_output``），
    不内联整份 schema 文本。
    """

    AGENT_NAME = "chapter_writer_agent"
    WORKFLOW_NAME = "chapter_generation"
    # 描述「Assembler 核心 + 服务层合并字段」后的 LLM 输入；用于 input_schema 校验（与 orchestration 对齐）。
    CHAPTER_INPUT_SCHEMA = {
        "type": "object",
        "required": [
            "step_key",
            "workflow_type",
            "role_id",
            "project",
            "goal",
            "target_words",
            "state",
            "output_format",
        ],
        "properties": {
            "step_key": {"type": "string"},
            "workflow_type": {"type": "string"},
            "role_id": {"type": "string"},
            "project": {"type": "object"},
            "outline": {"type": "object"},
            "state": {"type": "object"},
            "retrieval": {"type": "object"},
            "working_notes": {"type": "object"},
            "goal": {"type": "string", "minLength": 1},
            "target_words": {"type": "integer", "minimum": 300, "maximum": 10000},
            "style_hint": {"type": ["string", "null"]},
            "writing_contract": {"type": "object"},
            "local_data_tools": {"type": "array"},
            "output_format": {"type": "object"},
        },
        "additionalProperties": True,
    }
    # 无 registry 时的扁平回退输出（非 writer 信封）；有 registry 时用 runtime response_schema。
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
    CHAPTER_EXPAND_OUTPUT_SCHEMA = {
        "type": "object",
        "required": ["content"],
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string", "minLength": 1},
            "summary": {"type": "string"},
            "notes": {"type": "string"},
        },
        "additionalProperties": True,
    }
    CHAPTER_EXPAND_INPUT_SCHEMA = {
        "type": "object",
        "required": [
            "task",
            "project",
            "goal",
            "target_words",
            "allowed_min",
            "allowed_max",
            "previous_draft",
            "must_keep",
            "growth_contract",
            "reference_constraints",
            "output_contract",
        ],
        "properties": {
            "task": {"type": "string"},
            "project": {"type": "object"},
            "goal": {"type": "string", "minLength": 1},
            "style_hint": {"type": ["string", "null"]},
            "target_words": {"type": "integer"},
            "allowed_min": {"type": "integer"},
            "allowed_max": {"type": "integer"},
            "previous_draft": {"type": "object"},
            "must_keep": {"type": "array"},
            "growth_contract": {"type": "object"},
            "reference_constraints": {"type": "object"},
            "output_contract": {"type": "object"},
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
        self._prompt_assembler = PromptPayloadAssembler()

    @staticmethod
    def _notify_live_progress(request: ChapterGenerationRequest, payload: dict[str, Any]) -> None:
        """将章节草稿 LLM 重试进度推送给编排层（写入 workflow_step.input_json.live_progress）。"""
        cb = request.live_progress_callback
        if cb is None:
            return
        try:
            cb(payload)
        except Exception:
            logger.debug("live_progress_callback 更新失败", exc_info=True)

    @staticmethod
    def _notify_checkpoint(request: ChapterGenerationRequest, payload: dict[str, Any]) -> None:
        """将可恢复草稿快照推送给编排层（写入 workflow_step.checkpoint_json）。"""
        cb = request.checkpoint_callback
        if cb is None:
            return
        try:
            cb(payload)
        except Exception:
            logger.debug("checkpoint_callback 更新失败", exc_info=True)

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
                    "enforce_chapter_word_count": bool(request.enforce_chapter_word_count),
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

                tw = int(request.target_words)
                if tw < 300 or tw > 10_000:
                    raise ChapterGenerationWorkflowError("target_words 必须在 300~10000 之间")
                token_budget_eff = chapter_context_token_budget(tw, explicit=request.context_token_budget)

                retrieval_call = self.tool_call_repo.create_call(
                    trace_id=trace_id,
                    agent_run_id=run_row.id,
                    tool_name="project_memory_retrieval",
                    input_json={
                        "project_id": str(request.project_id),
                        "query": writing_goal,
                        "top_k": int(request.include_memory_top_k),
                        "context_token_budget": int(token_budget_eff),
                    },
                )
                self.tool_call_repo.start(retrieval_call.id)
                active_tool_call_id = retrieval_call.id

                memory_context = self.project_memory_service.build_context(
                    project_id=request.project_id,
                    query=writing_goal,
                    token_budget=max(
                        400,
                        int(token_budget_eff),
                    ),
                    top_k=max(1, int(request.include_memory_top_k)),
                    chat_turns=request.chat_turns,
                    working_notes=request.working_notes,
                )
                relevance_blob = build_writer_relevance_blob(
                    writing_goal,
                    request.orchestrator_raw_state,
                )
                if env_bool("WRITER_STORY_CONTEXT_LOAD_FOCUS", True):
                    story_context = self.story_context_provider.load_focused(
                        project_id=request.project_id,
                        chapter_no=request.chapter_no,
                        relevance_blob=relevance_blob,
                    )
                else:
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

                runtime = dict(
                    self._resolve_writer_runtime(
                        workflow_type=self.WORKFLOW_NAME,
                        step_key="writer_draft",
                        strategy_mode="draft",
                    )
                )
                computed_out = chapter_max_output_tokens(tw)
                base_mt = runtime.get("max_tokens")
                if isinstance(base_mt, int):
                    runtime["max_tokens"] = max(int(base_mt), int(computed_out))
                else:
                    runtime["max_tokens"] = int(computed_out)
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
                skill_specs, skill_filter_warnings = self._filter_draft_skills(
                    skills=skill_specs,
                    target_words=tw,
                )
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
                runtime_warnings.extend(list(skill_filter_warnings or []))

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
                w_low, w_high = chapter_word_count_allowed_range(tw)
                # user JSON：_build_chapter_writer_prompt_payload 内先 PromptPayloadAssembler.build（StepInputSpec
                # writer_draft / chapter_draft），再合并 goal / writing_contract / output_format；无 _build_user_prompt。
                base_prompt_payload = self._build_chapter_writer_prompt_payload(
                    project=project,
                    writing_goal=writing_goal,
                    target_words=request.target_words,
                    style_hint=request.style_hint,
                    memory_context=memory_context,
                    story_context=story_context,
                    working_notes=request.working_notes,
                    retrieval_context=request.retrieval_context,
                    chapter_no=request.chapter_no,
                    word_count_min=w_low,
                    word_count_max=w_high,
                    using_writer_schema=bool(runtime.get("using_writer_schema")),
                    output_format_schema_ref=str(runtime.get("output_format_schema_ref") or ""),
                    output_format_contract=str(runtime.get("output_format_contract") or ""),
                    orchestrator_raw_state=request.orchestrator_raw_state,
                )

                max_word_attempts = max(1, min(10, int(os.environ.get("WRITER_CHAPTER_WORD_COUNT_MAX_ATTEMPTS", "3"))))
                short_expand_enabled = self._env_flag("WRITER_CHAPTER_TOO_SHORT_EXPAND_ENABLED", default=True)
                short_expand_trigger_attempt = max(
                    2,
                    min(
                        10,
                        int(os.environ.get("WRITER_CHAPTER_TOO_SHORT_EXPAND_TRIGGER_ATTEMPT", "3")),
                    ),
                )
                last_bad_wc: int | None = None
                last_bad_raw_len: int | None = None
                last_issue: str | None = None
                llm_output: Any = None
                before: Any = None
                after: Any = None
                writer_structured: dict[str, Any] = {}
                legacy: dict[str, str] = {}
                draft_title = ""
                draft_content = ""
                draft_summary = ""
                recoverable_title = ""
                recoverable_summary = ""
                recoverable_content = ""
                wc = 0
                short_expand_no_progress_streak = 0
                schema_progressive = self._env_flag("WRITER_CHAPTER_SCHEMA_MIN_PROGRESSIVE", default=True)
                # 字数多轮仍不达标时是否用最后一轮草稿放行（关闭则维持抛错）。
                word_count_final_bypass = self._env_flag(
                    "WRITER_CHAPTER_WORD_COUNT_FINAL_BYPASS",
                    default=True,
                )
                word_count_bypass_warning: str | None = None
                enforce_wc = bool(request.enforce_chapter_word_count)

                for word_attempt in range(max_word_attempts):
                    schema_min_content_len = self._schema_min_content_len_for_attempt(
                        w_low=w_low,
                        word_attempt=word_attempt,
                        progressive_enabled=schema_progressive,
                    )
                    draft_pool_title = (draft_title or recoverable_title).strip()
                    draft_pool_summary = (draft_summary or recoverable_summary).strip()
                    draft_pool_content = (draft_content or recoverable_content).strip()
                    use_short_expander = self._should_use_short_draft_expander(
                        enabled=short_expand_enabled,
                        attempt_index=word_attempt,
                        trigger_attempt=short_expand_trigger_attempt,
                        issue=last_issue,
                        previous_content=draft_pool_content,
                        no_progress_streak=short_expand_no_progress_streak,
                        enforce_word_count=enforce_wc,
                    )
                    prompt_payload = copy.deepcopy(base_prompt_payload)
                    if (
                        enforce_wc
                        and word_attempt > 0
                        and last_bad_wc is not None
                        and last_issue is not None
                    ):
                        contract = dict(prompt_payload.get("writing_contract") or {})
                        contract["word_count_retry"] = self._word_count_retry_contract(
                            attempt_index=word_attempt,
                            max_attempts=max_word_attempts,
                            effective_chars=last_bad_wc,
                            low=w_low,
                            high=w_high,
                            target_words=tw,
                            issue=last_issue,
                            previous_raw_char_len=last_bad_raw_len,
                            flat_output=use_short_expander,
                        )
                        prompt_payload["writing_contract"] = contract

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
                    generation_mode = "expand_short_draft" if use_short_expander else "full_regenerate"
                    _llm_diag_logger.info(
                        "[chapter_generation] writer_draft_generation_mode | attempt=%s/%s mode=%s "
                        "enabled=%s trigger_attempt=%s prev_issue=%s prev_wc=%s schema_min_len=%s",
                        word_attempt + 1,
                        max_word_attempts,
                        generation_mode,
                        short_expand_enabled,
                        short_expand_trigger_attempt,
                        last_issue,
                        last_bad_wc,
                        schema_min_content_len,
                    )
                    self._notify_live_progress(
                        request,
                        {
                            "kind": "writer_draft_llm",
                            "attempt": int(word_attempt) + 1,
                            "max_attempts": int(max_word_attempts),
                            "generation_mode": generation_mode,
                            "issue": last_issue,
                            "schema_min_content_len": int(schema_min_content_len),
                            "pulse_at": datetime.now(tz=timezone.utc).isoformat(),
                            "llm_timeout_seconds": float(
                                getattr(self.text_provider, "timeout_seconds", 120.0)
                            ),
                        },
                    )

                    llm_call = None
                    try:
                        if use_short_expander:
                            llm_call = self.tool_call_repo.create_call(
                                trace_id=trace_id,
                                agent_run_id=run_row.id,
                                tool_name="llm_expand_chapter",
                                input_json={
                                    "target_words": int(request.target_words),
                                    "temperature": float(runtime_temp),
                                    "style_hint": request.style_hint,
                                    "strategy_version": runtime.get("strategy_version"),
                                    "schema_ref": runtime.get("schema_ref"),
                                    "generation_mode": generation_mode,
                                    "word_count_attempt": int(word_attempt) + 1,
                                    "word_count_max_attempts": int(max_word_attempts),
                                },
                            )
                            self.tool_call_repo.start(llm_call.id)
                            active_tool_call_id = llm_call.id

                            expander_prompt = self._build_short_draft_expander_prompt(
                                project=project,
                                writing_goal=writing_goal,
                                style_hint=request.style_hint,
                                target_words=tw,
                                low=w_low,
                                high=w_high,
                                previous_title=draft_pool_title or draft_title,
                                previous_summary=draft_pool_summary or draft_summary,
                                previous_content=draft_pool_content,
                                prompt_payload=prompt_payload,
                            )
                            llm_output = self.text_provider.generate(
                                TextGenerationRequest(
                                    system_prompt=self._short_draft_expander_system_prompt(),
                                    user_prompt=json.dumps(expander_prompt, ensure_ascii=False),
                                    temperature=min(0.45, float(runtime_temp)),
                                    max_tokens=runtime_max_tokens,
                                    input_payload=expander_prompt,
                                    input_schema=self.CHAPTER_EXPAND_INPUT_SCHEMA,
                                    input_schema_name="chapter_expand_input",
                                    input_schema_strict=True,
                                    response_schema=self._build_response_schema_with_content_min(
                                        self.CHAPTER_EXPAND_OUTPUT_SCHEMA,
                                        min_content_len=schema_min_content_len,
                                    ),
                                    response_schema_name="chapter_expand_output",
                                    response_schema_strict=True,
                                    validation_retries=2,
                                    use_function_calling=True,
                                    function_name="chapter_expand_output",
                                    function_description=(
                                        "Return expanded chapter JSON where content length satisfies requested range."
                                    ),
                                    metadata_json={
                                        "target_words": request.target_words,
                                        "workflow": self.WORKFLOW_NAME,
                                        "trace_id": trace_id,
                                        "strategy_version": runtime.get("strategy_version"),
                                        "schema_ref": runtime.get("schema_ref"),
                                        "generation_mode": generation_mode,
                                        "word_count_attempt": int(word_attempt) + 1,
                                        "word_count_max_attempts": int(max_word_attempts),
                                    },
                                )
                            )
                            expanded = dict(llm_output.json_data or {})
                            chapter_map = (
                                dict(expanded.get("chapter") or {})
                                if isinstance(expanded.get("chapter"), dict)
                                else {}
                            )
                            expanded_title = str(
                                chapter_map.get("title") or expanded.get("title") or draft_title or "未命名章节"
                            ).strip()
                            expanded_content = str(
                                chapter_map.get("content") or expanded.get("content") or ""
                            ).strip()
                            expanded_summary = str(
                                chapter_map.get("summary") or expanded.get("summary") or draft_summary or ""
                            ).strip()
                            writer_structured = {
                                "mode": "draft",
                                "status": "success",
                                "segments": [],
                                "word_count": count_fiction_word_units(expanded_content),
                                "notes": str(expanded.get("notes") or "").strip(),
                                "chapter": {
                                    "title": expanded_title or "未命名章节",
                                    "content": expanded_content,
                                    "summary": expanded_summary,
                                },
                            }
                        else:
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
                                    "generation_mode": generation_mode,
                                    "word_count_attempt": int(word_attempt) + 1,
                                    "word_count_max_attempts": int(max_word_attempts),
                                },
                            )
                            self.tool_call_repo.start(llm_call.id)
                            active_tool_call_id = llm_call.id

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
                                    response_schema=self._build_response_schema_with_content_min(
                                        runtime.get("response_schema") or self.CHAPTER_OUTPUT_SCHEMA,
                                        min_content_len=schema_min_content_len,
                                    ),
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
                                        "generation_mode": generation_mode,
                                        "word_count_attempt": int(word_attempt) + 1,
                                        "word_count_max_attempts": int(max_word_attempts),
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
                    except Exception as gen_exc:
                        gen_exc_text = str(gen_exc or "")
                        if isinstance(gen_exc, ResponseSchemaValidationError) and gen_exc.json_data:
                            leg = self._legacy_chapter_from_raw_writer_json(
                                dict(gen_exc.json_data),
                            )
                            pc = str(leg.get("content") or "").strip()
                            if pc:
                                recoverable_content = pc
                                t_leg = str(leg.get("title") or "").strip()
                                s_leg = str(leg.get("summary") or "").strip()
                                if t_leg:
                                    recoverable_title = t_leg
                                if s_leg:
                                    recoverable_summary = s_leg
                                last_bad_wc = count_fiction_word_units(pc)
                                last_bad_raw_len = len(pc)
                                last_issue = "too_short"
                                _llm_diag_logger.info(
                                    "[chapter_generation] schema_reject_recoverable_draft | "
                                    "attempt=%s/%s raw_len=%s effective_non_ws=%s",
                                    word_attempt + 1,
                                    max_word_attempts,
                                    last_bad_raw_len,
                                    last_bad_wc,
                                )
                        # 旧逻辑曾在 schema 失败时把 minLength 按 0.75 递减，会让「契约下限」越降越低，
                        # 与「正文要写够 target_words±10%」背道而驰；默认关闭，仅排障时可开。
                        if self._env_flag("WRITER_CHAPTER_SCHEMA_MIN_RELAX_ON_FAIL", default=False) and (
                            "schema 校验" in gen_exc_text
                            or "长度不足" in gen_exc_text
                            or "minLength" in gen_exc_text
                        ):
                            prev_min = int(schema_min_content_len)
                            relax = float(os.environ.get("WRITER_CHAPTER_SCHEMA_MIN_RELAX_FACTOR", "0.75"))
                            relax = max(0.5, min(0.99, relax))
                            schema_min_content_len = max(1, int(schema_min_content_len * relax))
                            if schema_min_content_len != prev_min:
                                logger.warning(
                                    "章节草稿 schema 最小长度下调（WRITER_CHAPTER_SCHEMA_MIN_RELAX_ON_FAIL）| "
                                    "attempt=%s/%s mode=%s from=%s to=%s",
                                    word_attempt + 1,
                                    max_word_attempts,
                                    generation_mode,
                                    prev_min,
                                    schema_min_content_len,
                                )
                        if llm_call is not None:
                            self.tool_call_repo.fail(
                                llm_call.id,
                                error_code=type(gen_exc).__name__,
                                output_json={
                                    "error": str(gen_exc),
                                    "generation_mode": generation_mode,
                                    "word_count_attempt": int(word_attempt) + 1,
                                    "word_count_max_attempts": int(max_word_attempts),
                                },
                            )
                        active_tool_call_id = None
                        if word_attempt >= max_word_attempts - 1:
                            raise
                        if last_bad_wc is None:
                            last_bad_wc = 0
                        if last_bad_raw_len is None and isinstance(
                            gen_exc,
                            ResponseSchemaValidationError,
                        ):
                            last_bad_raw_len = 0
                        if last_issue is None:
                            last_issue = "too_short"
                        logger.warning(
                            "章节草稿生成失败，将进入下一次重试 | attempt=%s/%s mode=%s error=%s",
                            word_attempt + 1,
                            max_word_attempts,
                            generation_mode,
                            str(gen_exc),
                        )
                        continue
                    legacy = WriterOutputAdapter.legacy_chapter(writer_structured)
                    draft_title = str(legacy.get("title") or "").strip() or "未命名章节"
                    draft_content = str(legacy.get("content") or "").strip()
                    draft_summary = str(legacy.get("summary") or "").strip()
                    if not draft_content:
                        self.tool_call_repo.fail(
                            llm_call.id,
                            error_code="MISSING_CONTENT",
                            output_json={"word_count_attempt": int(word_attempt) + 1},
                        )
                        active_tool_call_id = None
                        if word_attempt >= max_word_attempts - 1:
                            raise ChapterGenerationWorkflowError("LLM 输出缺少 content")
                        last_bad_wc = 0
                        last_bad_raw_len = 0
                        last_issue = "too_short"
                        logger.warning(
                            "章节草稿缺少正文，将重试 | attempt=%s/%s",
                            word_attempt + 1,
                            max_word_attempts,
                        )
                        continue

                    wc = count_fiction_word_units(draft_content)
                    if use_short_expander:
                        base_wc = int(last_bad_wc or 0)
                        growth = int(wc - base_wc)
                        min_expected_growth = max(120, int(tw * 0.05))
                        if growth < min_expected_growth:
                            short_expand_no_progress_streak += 1
                        else:
                            short_expand_no_progress_streak = 0
                    else:
                        short_expand_no_progress_streak = 0
                    try:
                        llm_dump_len = len(
                            json.dumps(dict(llm_output.json_data or {}), ensure_ascii=False)
                        )
                    except Exception:
                        llm_dump_len = -1
                    seg_list = (
                        list(writer_structured.get("segments") or [])
                        if isinstance(writer_structured.get("segments"), list)
                        else []
                    )
                    seg_join = "\n".join(
                        str(s.get("content") or "").strip()
                        for s in seg_list
                        if isinstance(s, dict)
                    )
                    seg_join_eff = count_fiction_word_units(seg_join)
                    seg_n = len([s for s in seg_list if isinstance(s, dict)])
                    _llm_diag_logger.info(
                        "[chapter_generation] writer_draft_lens | attempt=%s/%s "
                        "llm_primary_text_len=%d llm_json_dump_len=%d "
                        "legacy_content_strlen=%d legacy_content_non_ws=%d "
                        "segments_n=%d segments_join_non_ws=%d",
                        word_attempt + 1,
                        max_word_attempts,
                        len(llm_output.text or ""),
                        llm_dump_len,
                        len(draft_content),
                        wc,
                        seg_n,
                        seg_join_eff,
                    )
                    _llm_diag_logger.info(
                        "[chapter_generation] writer_draft_word_stats | attempt=%s/%s "
                        "target_words=%s allowed=[%s,%s] actual_non_ws=%s "
                        "gap_to_min=%s gap_to_max=%s issue=%s",
                        word_attempt + 1,
                        max_word_attempts,
                        tw,
                        w_low,
                        w_high,
                        wc,
                        wc - w_low,
                        w_high - wc,
                        "ok" if (w_low <= wc <= w_high) else ("too_short" if wc < w_low else "too_long"),
                    )
                    self._notify_checkpoint(
                        request,
                        {
                            "kind": "writer_draft_partial",
                            "draft_title": (draft_title or "")[:2000],
                            "draft_summary": (draft_summary or "")[:4000],
                            "draft_content": (draft_content or "")[:12000],
                            "word_attempt_index": int(word_attempt),
                            "generation_mode": generation_mode,
                            "effective_wc": wc,
                            "schema_min_content_len": int(schema_min_content_len),
                            "last_issue": last_issue,
                            "word_count_enforced": enforce_wc,
                        },
                    )
                    if not enforce_wc:
                        break
                    if w_low <= wc <= w_high:
                        break

                    last_bad_wc = wc
                    last_bad_raw_len = len(draft_content)
                    last_issue = "too_short" if wc < w_low else "too_long"
                    logger.info(
                        "章节草稿字数未达标，准备让模型重写 | attempt=%s/%s wc=%s 允许=[%s,%s] issue=%s",
                        word_attempt + 1,
                        max_word_attempts,
                        wc,
                        w_low,
                        w_high,
                        last_issue,
                    )
                    is_last_attempt = word_attempt >= max_word_attempts - 1
                    if is_last_attempt and word_count_final_bypass:
                        _llm_diag_logger.warning(
                            "[chapter_generation] writer_draft 字数未达标已达最大次数，使用本轮草稿放行 | "
                            "attempt=%s/%s llm_json_dump_len=%s legacy_content_non_ws=%s segments_join_non_ws=%s",
                            word_attempt + 1,
                            max_word_attempts,
                            llm_dump_len,
                            wc,
                            seg_join_eff,
                        )
                        base = chapter_word_count_violation_message(
                            effective_chars=wc,
                            target_words=tw,
                            low=w_low,
                            high=w_high,
                        )
                        word_count_bypass_warning = (
                            f"{base}已达最大重写次数 {max_word_attempts}，已使用本轮输出放行。"
                        )
                        logger.warning(word_count_bypass_warning)
                        break

                    self.tool_call_repo.fail(
                        llm_call.id,
                        error_code="CHAPTER_WORD_COUNT",
                        output_json={
                            "effective_chars": wc,
                            "allowed_min": w_low,
                            "allowed_max": w_high,
                            "target_words": tw,
                            "will_retry": not is_last_attempt,
                            "word_count_attempt": int(word_attempt) + 1,
                        },
                    )
                    active_tool_call_id = None
                    if is_last_attempt:
                        _llm_diag_logger.warning(
                            "[chapter_generation] writer_draft 仍不达标，放弃重写 | "
                            "attempt=%s/%s llm_json_dump_len=%s legacy_content_non_ws=%s segments_join_non_ws=%s",
                            word_attempt + 1,
                            max_word_attempts,
                            llm_dump_len,
                            wc,
                            seg_join_eff,
                        )
                        base = chapter_word_count_violation_message(
                            effective_chars=wc,
                            target_words=tw,
                            low=w_low,
                            high=w_high,
                        )
                        raise ChapterGenerationWorkflowError(
                            f"{base}已达最大重写次数 {max_word_attempts}。"
                        )

                self._notify_live_progress(request, {"kind": "idle"})

                skill_runs_payload = self._build_skill_runs_payload(
                    skills=skill_specs,
                    before_runs=list(getattr(before, "runs", []) or []),
                    after_runs=list(getattr(after, "runs", []) or []),
                )
                for run_id, snapshot in zip(active_skill_run_ids, skill_runs_payload):
                    self.skill_run_repo.succeed(run_id, output_snapshot_json=snapshot)
                active_skill_run_ids = []

                all_warnings = []
                all_warnings.extend(runtime_warnings)
                all_warnings.extend(
                    [str(item) for item in list(getattr(before, "warnings", []) or []) if str(item).strip()]
                )
                all_warnings.extend(
                    [str(item) for item in list(getattr(after, "warnings", []) or []) if str(item).strip()]
                )
                if word_count_bypass_warning:
                    all_warnings.append(word_count_bypass_warning)
                if not enforce_wc:
                    all_warnings.append(
                        "已关闭「生成正文字数」契约校验；target_words 仍会提供给模型作为写作参考。"
                    )

                self.tool_call_repo.succeed(
                    llm_call.id,
                    output_json={
                        "provider": llm_output.provider,
                        "model": llm_output.model,
                        "is_mock": llm_output.is_mock,
                        "skills_effective_delta": int(
                            sum(int(item.get("effective_delta") or 0) for item in skill_runs_payload)
                        ),
                        "word_count_contract_bypassed": bool(word_count_bypass_warning),
                        "word_count_enforced": enforce_wc,
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
                self._notify_live_progress(request, {"kind": "idle"})
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
            "output_format_schema_ref": WRITER_OUTPUT_SCHEMA_REF_LEGACY_INLINE,
            "output_format_contract": WRITER_OUTPUT_CONTRACT_LEGACY_FLAT,
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

        # 解析 response_schema 来源，供 using_writer_schema 与真实生效的校验 schema 对齐（勿仅用 profile.output_schema）。
        schema_payload: dict[str, Any] | None = None
        schema_resolution: str = "fallback_flat"
        if isinstance(profile.output_schema, dict) and profile.output_schema:
            schema_payload = dict(profile.output_schema)
            schema_resolution = "profile_inline"
        elif self.schema_registry is not None:
            loaded = self.schema_registry.get(profile.schema_ref)
            if isinstance(loaded, dict) and loaded:
                schema_payload = dict(loaded)
                schema_resolution = "registry"

        if not isinstance(schema_payload, dict) or not schema_payload:
            schema_payload = dict(self.CHAPTER_OUTPUT_SCHEMA)
            schema_resolution = "fallback_flat"

        system_prompt = profile.prompt or self._legacy_system_prompt()
        mode = str(strategy_mode or "").strip().lower()
        draft_schema_warnings: list[str] = []
        draft_schema_active = False
        if mode == "draft" and self.agent_registry is not None:
            draft_path = self.agent_registry.root / "writer_agent" / "prompt_draft.md"
            if draft_path.is_file():
                system_prompt = self.agent_registry.compose_prompt_with_shared_tools(
                    draft_path.read_text(encoding="utf-8").strip(),
                )
            draft_schema_path = self.agent_registry.root / "writer_agent" / "output_schema_draft.json"
            if draft_schema_path.is_file():
                try:
                    loaded_draft = json.loads(draft_schema_path.read_text(encoding="utf-8"))
                    if isinstance(loaded_draft, dict) and loaded_draft:
                        schema_payload = loaded_draft
                        draft_schema_active = True
                        schema_resolution = "draft"
                except Exception as exc:
                    draft_schema_warnings.append(
                        f"output_schema_draft.json 解析失败，沿用全量 schema: {exc}"
                    )

        merged_warnings = [str(item) for item in list(warnings or []) if str(item).strip()]
        merged_warnings.extend(draft_schema_warnings)

        # user payload.output_format 须与真实校验用的 response_schema 一致，避免软提示与 FC/json_schema 硬约束打架。
        if draft_schema_active:
            output_format_schema_ref = WRITER_OUTPUT_SCHEMA_REF_DRAFT
            output_format_contract = WRITER_OUTPUT_CONTRACT_DRAFT
        else:
            output_format_schema_ref = WRITER_OUTPUT_SCHEMA_REF_V2
            output_format_contract = WRITER_OUTPUT_CONTRACT_V2

        using_writer_schema = schema_resolution != "fallback_flat"

        return {
            "system_prompt": system_prompt,
            "response_schema": schema_payload,
            "temperature": float(strategy.temperature),
            "max_tokens": int(strategy.max_tokens),
            "skills": list(skills or []),
            "warnings": merged_warnings,
            "schema_ref": profile.schema_ref,
            "schema_version": profile.schema_version,
            "strategy_version": strategy.version,
            "using_writer_schema": using_writer_schema,
            "output_format_schema_ref": output_format_schema_ref,
            "output_format_contract": output_format_contract,
        }

    @staticmethod
    def _filter_draft_skills(
        *,
        skills: list[SkillSpec],
        target_words: int,
    ) -> tuple[list[SkillSpec], list[str]]:
        """
        长章节写作时避免注入促使过度压缩的技能提示。

        说明：`text_refinement` 会追加“保持文本简洁”的系统提示，容易与长章节字数契约冲突。
        """
        if int(target_words) < 2000:
            return list(skills or []), []

        blocked = {"text_refinement"}
        kept: list[SkillSpec] = []
        removed: list[str] = []
        for spec in list(skills or []):
            sid = str(getattr(spec, "id", "") or "").strip().lower()
            if sid in blocked:
                removed.append(sid)
                continue
            kept.append(spec)

        if not removed:
            return kept, []
        warning = (
            "long-form draft 已自动禁用易压缩正文的技能: "
            + ", ".join(sorted(set(removed)))
            + f"（target_words={int(target_words)}）"
        )
        return kept, [warning]

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

    @staticmethod
    def _env_flag(name: str, *, default: bool) -> bool:
        raw = str(os.environ.get(name, "1" if default else "0")).strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
        return bool(default)

    @staticmethod
    def _legacy_chapter_from_raw_writer_json(data: dict[str, Any]) -> dict[str, str]:
        """从 Writer 原始 JSON 抽取 chapter 三字段（不经过 Adapter），用于 schema 失败时回收短稿。"""
        ch = dict(data.get("chapter") or {}) if isinstance(data.get("chapter"), dict) else {}
        title = str(ch.get("title") or data.get("title") or "").strip()
        content = str(ch.get("content") or data.get("content") or "").strip()
        summary = str(ch.get("summary") or data.get("summary") or "").strip()
        return {"title": title, "content": content, "summary": summary}

    @staticmethod
    def _schema_min_content_len_for_attempt(
        *,
        w_low: int,
        word_attempt: int,
        progressive_enabled: bool,
    ) -> int:
        """
        结构化输出层的 content.minLength（按 Python len，含空白），刻意低于业务低线 w_low，
        避免「首层 schema = 终局契约」导致无草稿、扩写永不触发。
        """
        w_low = max(1, int(w_low))
        soft_ratio = float(os.environ.get("WRITER_CHAPTER_SCHEMA_CONTENT_SOFT_MIN_RATIO", "0.58"))
        soft_ratio = max(0.35, min(0.92, soft_ratio))
        abs_frac = float(os.environ.get("WRITER_CHAPTER_SCHEMA_SOFT_ABS_FRAC", "0.22"))
        abs_frac = max(0.08, min(0.45, abs_frac))
        min_abs = max(1, int(w_low * abs_frac))
        tier_factors = (1.0, 0.9, 0.8, 0.72, 0.64, 0.56)
        idx = min(max(0, int(word_attempt)), len(tier_factors) - 1)
        tier = tier_factors[idx] if progressive_enabled else 1.0
        raw = int(w_low * soft_ratio * tier)
        return max(min_abs, min(raw, w_low - 1))

    @staticmethod
    def _should_use_short_draft_expander(
        *,
        enabled: bool,
        attempt_index: int,
        trigger_attempt: int,
        issue: str | None,
        previous_content: str | None,
        no_progress_streak: int = 0,
        enforce_word_count: bool = True,
    ) -> bool:
        if not bool(enforce_word_count):
            return False
        if not bool(enabled):
            return False
        if int(attempt_index) + 1 < int(trigger_attempt):
            return False
        if str(issue or "").strip().lower() != "too_short":
            return False
        # 扩写连续无增量时回退完整重写，避免在同一短稿上重复打转。
        if int(no_progress_streak) > 0:
            return False
        return bool(str(previous_content or "").strip())

    @staticmethod
    def _short_draft_expander_system_prompt() -> str:
        return (
            "你是长篇小说扩写助手。"
            "目标是在不改变关键剧情事实与因果顺序的前提下，将正文扩写到指定字数区间。"
            "只输出 JSON 对象，字段可为 title/content/summary。"
            "严禁输出 Markdown、解释文本或省略号占位。"
        )

    @staticmethod
    def _build_short_draft_expander_prompt(
        *,
        project,
        writing_goal: str,
        style_hint: str | None,
        target_words: int,
        low: int,
        high: int,
        previous_title: str,
        previous_summary: str,
        previous_content: str,
        prompt_payload: dict[str, Any],
    ) -> dict[str, Any]:
        prev_effective = count_fiction_word_units(str(previous_content or ""))
        required_growth = max(0, int(low) - int(prev_effective))
        return {
            "task": "expand_short_draft",
            "project": {
                "id": str(project.id),
                "title": project.title,
                "genre": project.genre,
            },
            "goal": str(writing_goal or "").strip(),
            "style_hint": str(style_hint or "").strip() or None,
            "target_words": int(target_words),
            "allowed_min": int(low),
            "allowed_max": int(high),
            "previous_draft": {
                "title": str(previous_title or "").strip(),
                "summary": str(previous_summary or "").strip(),
                "content": str(previous_content or "").strip(),
                "effective_chars": prev_effective,
            },
            "must_keep": [
                "保留核心事件顺序与关键事实，不要改写成另一个故事。",
                "扩写应以具体场景、动作、对白、心理活动推进，不要写提纲。",
                "正文必须是连续叙事，不要输出 bullet list。",
                "最终 content 的非空白字符数必须落在允许区间内。",
                f"相对上一稿，content 至少新增 {required_growth} 个非空白字符（若上一稿已达标则保持在区间内）。",
            ],
            "growth_contract": {
                "previous_effective_chars": int(prev_effective),
                "required_effective_chars_at_least": int(low),
                "required_growth_at_least": int(required_growth),
            },
            "reference_constraints": {
                "writing_contract": dict(prompt_payload.get("writing_contract") or {}),
                "state": dict(prompt_payload.get("state") or {}),
                "retrieval": dict(prompt_payload.get("retrieval") or {}),
            },
            "output_contract": {
                "required_fields": ["content"],
                "optional_fields": ["title", "summary"],
                "content_must_be_full_chapter": True,
            },
        }

    @staticmethod
    def _build_response_schema_with_content_min(
        base_schema: dict[str, Any],
        *,
        min_content_len: int,
    ) -> dict[str, Any]:
        """
        对 content 字段动态注入最小长度约束（按 Python len，含空白）。

        注入值应低于业务低线（见 _schema_min_content_len_for_attempt），
        仅作「别太短的草稿」软门槛；终局仍以非空白字数与 [w_low,w_high] 为准。
        """
        schema = copy.deepcopy(dict(base_schema or {}))
        min_len = max(1, int(min_content_len))

        def _patch_content(props: Any) -> None:
            if not isinstance(props, dict):
                return
            content_node = props.get("content")
            if isinstance(content_node, dict):
                old = content_node.get("minLength")
                try:
                    old_val = int(old) if old is not None else 0
                except Exception:
                    old_val = 0
                content_node["minLength"] = max(min_len, old_val)

        root_props = schema.get("properties")
        if isinstance(root_props, dict):
            _patch_content(root_props)
            chapter_node = root_props.get("chapter")
            if isinstance(chapter_node, dict):
                _patch_content(chapter_node.get("properties"))
        return schema

    @staticmethod
    def _word_count_retry_contract(
        *,
        attempt_index: int,
        max_attempts: int,
        effective_chars: int,
        low: int,
        high: int,
        target_words: int,
        issue: str,
        previous_raw_char_len: int | None = None,
        flat_output: bool = False,
    ) -> dict[str, Any]:
        """上一稿字数不达标时注入 writing_contract，驱动模型在后续轮次重写。"""
        content_ref = "`content`" if flat_output else "`chapter.content`"
        metric_note = ""
        if previous_raw_char_len is not None:
            metric_note = (
                f"上一轮 {content_ref} 原始字符数（含空白）约 {int(previous_raw_char_len)}，"
                f"有效非空白字约 {int(effective_chars)}；请在此基础上扩写或压缩，避免误解为「零字稿」。"
            )
        return {
            "round": int(attempt_index) + 1,
            "max_rounds": int(max_attempts),
            "previous_effective_chars": int(effective_chars),
            "previous_raw_char_len": previous_raw_char_len,
            "allowed_min": int(low),
            "allowed_max": int(high),
            "must_reach_effective_chars_at_least": int(low),
            "must_not_exceed_effective_chars": int(high),
            "target_words": int(target_words),
            "issue": str(issue),
            "instruction_cn": (
                "上一稿未满足字数契约：请重新输出**完整** JSON。"
                f"{content_ref} 的「非空白字符数」必须落在 [{low}, {high}]（target_words={target_words}）。"
                "禁止仅用摘要、大纲式 bullet 或极短片段凑数；请充分展开场景、对白与描写。"
                "输出结束前必须先自检非空白字符数是否达标。"
                + metric_note
                + (
                    " 当前偏短，请优先扩展有效剧情、对白和动作细节，直到达到最小值。"
                    if issue == "too_short"
                    else " 当前偏长，请压缩冗余描写并保持情节完整。"
                )
            ),
        }

    @staticmethod
    def _build_chapter_retrieval_bundle(
        *,
        memory_items: list[dict[str, Any]],
        orchestrator_retrieval_text: str | None,
    ) -> dict[str, Any]:
        """章节独立链路：用记忆条目 + 编排侧检索摘要构造 Assembler 所需的 retrieval_bundle。"""
        items: list[dict[str, Any]] = []
        for it in memory_items:
            items.append(
                {
                    "source": str(it.get("source") or "memory"),
                    "score": it.get("priority"),
                    "text": str(it.get("text") or "")[:8000],
                }
            )
        key_facts: list[str] = []
        text = str(orchestrator_retrieval_text or "").strip()
        if text:
            key_facts.append(text[:12000])
        return {
            "summary": {"key_facts": key_facts, "current_states": []},
            "items": items,
            "meta": {},
        }

    @staticmethod
    def _merge_retrieval_bundles(
        a: dict[str, Any],
        b: dict[str, Any],
    ) -> dict[str, Any]:
        """合并两路检索包：summary 拼接，items 串联（由 StepInputSpec 的 max_items 再截断）。"""
        sa = dict(a.get("summary") or {})
        sb = dict(b.get("summary") or {})
        kf = list(sa.get("key_facts") or []) + list(sb.get("key_facts") or [])
        cs = list(sa.get("current_states") or []) + list(sb.get("current_states") or [])
        items = list(a.get("items") or []) + list(b.get("items") or [])
        meta_a = a.get("meta") if isinstance(a.get("meta"), dict) else {}
        meta_b = b.get("meta") if isinstance(b.get("meta"), dict) else {}
        return {
            "summary": {"key_facts": kf, "current_states": cs},
            "items": items,
            "meta": {**dict(meta_a), **dict(meta_b)},
        }

    @staticmethod
    def _should_use_writer_draft_assembler(
        orchestrator_raw_state: dict[str, Any] | None,
    ) -> bool:
        """编排全链路下各 alignment 已就绪时使用 writer_agent:writer_draft 规格。"""
        if not orchestrator_raw_state:
            return False
        keys = (
            "outline_generation",
            "plot_alignment",
            "character_alignment",
            "world_alignment",
            "style_alignment",
        )
        return all(bool(orchestrator_raw_state.get(k)) for k in keys)

    @staticmethod
    def _snapshot_raw_state_for_chapter(raw_state: dict[str, Any]) -> dict[str, Any]:
        """浅拷贝各步骤输出，避免后续逻辑误改编排快照。"""
        out: dict[str, Any] = {}
        for k, v in raw_state.items():
            out[k] = copy.deepcopy(v) if isinstance(v, dict) else v
        return out

    def _build_chapter_writer_prompt_payload(
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
        chapter_no: int | None = None,
        word_count_min: int | None = None,
        word_count_max: int | None = None,
        using_writer_schema: bool,
        output_format_schema_ref: str = "",
        output_format_contract: str = "",
        orchestrator_raw_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """按 StepInputSpec 组装 LLM user JSON：先 PromptPayloadAssembler.build（writer_draft / chapter_draft），再合并 goal 等。

        ``retrieval_context`` 只写入 retrieval_bundle（见 ``retrieval`` 键），不作为顶层字段。
        ``output_format`` 由 runtime 的 ``writer.output.*`` 与 schema 路径常量决定，与 ``response_schema`` 一致。
        """
        project_context = {
            "id": str(project.id),
            "title": project.title,
            "genre": project.genre,
            "premise": project.premise,
            "metadata_json": project.metadata_json or {},
        }
        memory_items = [
            {"source": item.source, "text": item.text, "priority": item.priority}
            for item in memory_context.items
        ]
        relevance_blob = build_writer_relevance_blob(writing_goal, orchestrator_raw_state)
        writer_focus = build_writer_focus(chapter_no=chapter_no, relevance_blob=relevance_blob)
        writer_evidence_pack = build_writer_evidence_pack(story_context, chapter_no=chapter_no)
        story_snapshot = build_writer_context_slice(
            story_context,
            chapter_no=chapter_no,
            summary_first=env_bool("WRITER_STORY_ASSETS_SUMMARY_FIRST", True),
        )
        use_writer_draft = self._should_use_writer_draft_assembler(orchestrator_raw_state)
        if use_writer_draft:
            merged_raw = self._snapshot_raw_state_for_chapter(
                dict(orchestrator_raw_state or {})
            )
            merged_raw["writer_focus"] = {"view": writer_focus}
            merged_raw["writer_context_slice"] = {"view": story_snapshot}
            merged_raw["writer_evidence_pack"] = {"view": writer_evidence_pack}
            merged_raw["story_assets"] = {"view": story_snapshot}
            merged_raw["chapter_memory"] = {"items": memory_items}
            retrieval_bundle = build_retrieval_bundle_from_raw_state(merged_raw)
            mem_bundle = self._build_chapter_retrieval_bundle(
                memory_items=memory_items,
                orchestrator_retrieval_text=None,
            )
            retrieval_bundle = self._merge_retrieval_bundles(retrieval_bundle, mem_bundle)
            extra = str(retrieval_context or "").strip()
            if extra:
                summary = dict(retrieval_bundle.get("summary") or {})
                facts = list(summary.get("key_facts") or [])
                facts.insert(0, extra[:12000])
                retrieval_bundle = {
                    **retrieval_bundle,
                    "summary": {**summary, "key_facts": facts},
                }
            outline_state = dict(merged_raw.get("outline_generation") or {})
            core = self._prompt_assembler.build(
                role_id="writer_agent",
                step_key="writer_draft",
                workflow_type=self.WORKFLOW_NAME,
                project_context=project_context,
                raw_state=merged_raw,
                retrieval_bundle=retrieval_bundle,
                outline_state=outline_state,
                working_notes=working_notes,
            )
        else:
            raw_state: dict[str, dict[str, Any]] = {
                "chapter_memory": {"items": memory_items},
                "writer_focus": {"view": writer_focus},
                "writer_context_slice": {"view": story_snapshot},
                "writer_evidence_pack": {"view": writer_evidence_pack},
                "story_assets": {"view": story_snapshot},
            }
            retrieval_bundle = self._build_chapter_retrieval_bundle(
                memory_items=memory_items,
                orchestrator_retrieval_text=retrieval_context,
            )
            core = self._prompt_assembler.build(
                role_id="writer_agent",
                step_key="chapter_draft",
                workflow_type=self.WORKFLOW_NAME,
                project_context=project_context,
                raw_state=raw_state,
                retrieval_bundle=retrieval_bundle,
                outline_state={},
                working_notes=working_notes,
            )
        payload: dict[str, Any] = {
            **core,
            "goal": writing_goal,
            "target_words": int(target_words),
            "style_hint": style_hint,
            "writing_contract": {
                "word_count_metric": "非空白字符数",
                "word_count_allowed_min": int(word_count_min) if word_count_min is not None else None,
                "word_count_allowed_max": int(word_count_max) if word_count_max is not None else None,
                "chapter_no": int(chapter_no) if chapter_no is not None else None,
                "character_assets_note": (
                    "每位角色的 effective_inventory_json / effective_wealth_json 为当前章节创作应遵守的携带物与财富状态；"
                    "若剧情需要消耗/获得物品或财富，请在输出 notes 中列出变更建议，便于后续落库。"
                ),
            },
        }
        if using_writer_schema:
            schema_ref = (output_format_schema_ref or "").strip() or WRITER_OUTPUT_SCHEMA_REF_V2
            contract = (output_format_contract or "").strip() or WRITER_OUTPUT_CONTRACT_V2
            payload["output_format"] = {
                "schema_ref": schema_ref,
                "contract": contract,
            }
        else:
            payload["output_format"] = {
                "title": "string",
                "content": "string",
                "summary": "string",
            }
        if self.agent_registry is not None:
            payload["local_data_tools"] = self.agent_registry.local_data_tools_catalog()
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
