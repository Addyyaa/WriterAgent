from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from packages.llm.text_generation.base import TextGenerationProvider, TextGenerationRequest
from packages.llm.text_generation.runtime_config import TextGenerationRuntimeConfig
from packages.memory.long_term.ingestion.ingestion_service import MemoryIngestionService
from packages.schemas import SchemaRegistry
from packages.skills import SkillRuntimeContext, SkillRuntimeEngine
from packages.storage.postgres.repositories.chapter_repository import ChapterRepository
from packages.storage.postgres.repositories.consistency_report_repository import (
    ConsistencyReportRepository,
)
from packages.workflows.writer_output import WriterOutputAdapter

if TYPE_CHECKING:
    from packages.workflows.orchestration.agent_registry import AgentRegistry


@dataclass(frozen=True)
class RevisionRequest:
    project_id: object
    chapter_id: object
    trace_id: str | None = None
    force: bool = False
    retrieval_context: str | None = None


@dataclass(frozen=True)
class RevisionResult:
    revised: bool
    chapter_id: str
    version_id: int | None
    issues_count: int
    mock_mode: bool
    writer_structured: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    skill_runs: list[dict[str, Any]] = field(default_factory=list)


class RevisionWorkflowService:
    AGENT_NAME = "writer_agent"
    WORKFLOW_NAME = "revision"
    REVISION_INPUT_SCHEMA = {
        "type": "object",
        "required": ["chapter", "consistency_report", "output_schema"],
        "properties": {
            "chapter": {"type": "object"},
            "consistency_report": {"type": "object"},
            "retrieval_context": {"type": ["string", "null"]},
            "output_schema": {"type": "object"},
        },
        "additionalProperties": True,
    }
    # 兼容旧链路；当启用 writer_agent registry 时会使用 writer_agent/output_schema.json。
    REVISION_OUTPUT_SCHEMA = {
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
        chapter_repo: ChapterRepository,
        report_repo: ConsistencyReportRepository,
        ingestion_service: MemoryIngestionService,
        text_provider: TextGenerationProvider,
        agent_registry: AgentRegistry | None = None,
        schema_registry: SchemaRegistry | None = None,
        skill_runtime: SkillRuntimeEngine | None = None,
    ) -> None:
        self.chapter_repo = chapter_repo
        self.report_repo = report_repo
        self.ingestion_service = ingestion_service
        self.text_provider = text_provider
        self.agent_registry = agent_registry
        self.schema_registry = schema_registry
        self.skill_runtime = skill_runtime or SkillRuntimeEngine()

    def run(self, request: RevisionRequest) -> RevisionResult:
        chapter = self.chapter_repo.get(request.chapter_id)
        if chapter is None:
            raise RuntimeError("chapter 不存在")

        report = self.report_repo.get_latest_by_chapter(chapter_id=chapter.id)
        issues = list(report.issues_json or []) if report is not None else []

        if not request.force and (report is None or str(report.status) == "passed"):
            return RevisionResult(
                revised=False,
                chapter_id=str(chapter.id),
                version_id=None,
                issues_count=len(issues),
                mock_mode=True,
                writer_structured=None,
                warnings=[],
                skill_runs=[],
            )

        runtime = self._resolve_writer_runtime(
            workflow_type=self.WORKFLOW_NAME,
            step_key="writer_revision",
            strategy_mode="revision",
        )
        # revision_input 要求 output_schema 为 object；须传入真实 JSON Schema 字典供模型对齐，不可使用占位字符串。
        rs = runtime.get("response_schema")
        if isinstance(rs, dict) and rs:
            output_schema_for_payload = copy.deepcopy(rs)
        else:
            output_schema_for_payload = dict(self.REVISION_OUTPUT_SCHEMA)
        payload = {
            "chapter": {
                "title": chapter.title,
                "content": chapter.content,
                "summary": chapter.summary,
                "chapter_no": int(chapter.chapter_no),
            },
            "consistency_report": {
                "status": str(report.status) if report is not None else "warning",
                "summary": report.summary if report is not None else "",
                "issues": issues,
                "recommendations": list(report.recommendations_json or []) if report is not None else [],
            },
            "retrieval_context": request.retrieval_context,
            "output_schema": output_schema_for_payload,
        }

        before = self.skill_runtime.run_before_generate(
            skills=list(runtime.get("skills") or []),
            system_prompt=str(runtime.get("system_prompt") or self._legacy_system_prompt()),
            input_payload=payload,
            context=SkillRuntimeContext(
                trace_id=request.trace_id,
                role_id="writer_agent",
                workflow_type=self.WORKFLOW_NAME,
                step_key="writer_revision",
                mode="revision",
            ),
        )

        revision_timeout = TextGenerationRuntimeConfig.from_env().revision_llm_timeout_seconds
        llm_result = self.text_provider.generate(
            TextGenerationRequest(
                system_prompt=before.system_prompt,
                user_prompt=json.dumps(before.input_payload, ensure_ascii=False),
                temperature=float(runtime.get("temperature") or 0.4),
                max_tokens=(
                    int(runtime["max_tokens"])
                    if runtime.get("max_tokens") is not None
                    else None
                ),
                timeout_seconds=revision_timeout,
                input_payload=before.input_payload,
                input_schema=self.REVISION_INPUT_SCHEMA,
                input_schema_name="revision_input",
                input_schema_strict=True,
                response_schema=runtime.get("response_schema") or self.REVISION_OUTPUT_SCHEMA,
                response_schema_name="revision_output",
                response_schema_strict=True,
                validation_retries=2,
                use_function_calling=True,
                function_name="revision_output",
                function_description="Return revised chapter output JSON.",
                metadata_json={
                    "workflow": self.WORKFLOW_NAME,
                    "trace_id": request.trace_id,
                    "strategy_version": runtime.get("strategy_version"),
                    "schema_ref": runtime.get("schema_ref"),
                },
            )
        )

        after = self.skill_runtime.run_after_generate(
            skills=list(runtime.get("skills") or []),
            output_payload=dict(llm_result.json_data or {}),
            context=SkillRuntimeContext(
                trace_id=request.trace_id,
                role_id="writer_agent",
                workflow_type=self.WORKFLOW_NAME,
                step_key="writer_revision",
                mode="revision",
            ),
        )

        writer_structured = WriterOutputAdapter.normalize(
            dict(after.output_payload or {}),
            mode="revision",
        )
        legacy = WriterOutputAdapter.legacy_chapter(writer_structured)
        revised_title = str(legacy.get("title") or chapter.title or "").strip()
        revised_content = str(legacy.get("content") or "").strip() or str(chapter.content or "")
        revised_summary = str(legacy.get("summary") or chapter.summary or "").strip()

        chapter_row, version_row, _ = self.chapter_repo.save_generated_draft(
            project_id=request.project_id,
            chapter_no=int(chapter.chapter_no),
            title=revised_title,
            content=revised_content,
            summary=revised_summary,
            source_agent=self.AGENT_NAME,
            source_workflow=self.WORKFLOW_NAME,
            trace_id=request.trace_id,
        )

        self.ingestion_service.ingest_text(
            project_id=request.project_id,
            text=revised_content,
            source_type="chapter",
            source_id=chapter_row.id,
            chunk_type="chapter_body",
            metadata_json={
                "chapter_no": int(chapter_row.chapter_no),
                "trace_id": request.trace_id,
                "generated_by": self.AGENT_NAME,
                "source_workflow": self.WORKFLOW_NAME,
            },
            source_timestamp=datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            replace_existing=True,
        )

        all_warnings = []
        all_warnings.extend([str(item) for item in list(runtime.get("warnings") or []) if str(item).strip()])
        all_warnings.extend([str(item) for item in list(before.warnings or []) if str(item).strip()])
        all_warnings.extend([str(item) for item in list(after.warnings or []) if str(item).strip()])
        skill_runs = [
            {
                "skill_id": run.skill_id,
                "skill_version": run.skill_version,
                "phase": run.phase,
                "status": run.status,
                "skill_mode": run.skill_mode,
                "execution_mode": run.execution_mode,
                "mode_used": run.mode_used,
                "fallback_policy": run.fallback_policy,
                "fallback_used": run.fallback_used,
                "fallback_reason": run.fallback_reason,
                "applied": run.applied,
                "effective_delta": int(run.effective_delta),
                "warnings": list(run.warnings),
                "changed_spans": [dict(item) for item in list(run.changed_spans or []) if isinstance(item, dict)],
                "findings": [dict(item) for item in list(run.findings or []) if isinstance(item, dict)],
                "evidence": [dict(item) for item in list(run.evidence or []) if isinstance(item, dict)],
                "metrics": dict(run.metrics or {}),
                "no_effect_reason": run.no_effect_reason,
            }
            for run in [*list(before.runs or []), *list(after.runs or [])]
        ]

        return RevisionResult(
            revised=True,
            chapter_id=str(chapter_row.id),
            version_id=int(version_row.id),
            issues_count=len(issues),
            mock_mode=bool(llm_result.is_mock),
            writer_structured=writer_structured,
            warnings=all_warnings,
            skill_runs=skill_runs,
        )

    def _resolve_writer_runtime(
        self,
        *,
        workflow_type: str,
        step_key: str,
        strategy_mode: str,
    ) -> dict[str, Any]:
        default = {
            "system_prompt": self._legacy_system_prompt(),
            "response_schema": dict(self.REVISION_OUTPUT_SCHEMA),
            "temperature": 0.4,
            "max_tokens": None,
            "skills": [],
            "warnings": [],
            "schema_ref": "inline://revision/legacy_output",
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

        schema_resolution = "fallback_flat"
        schema_payload: dict[str, Any] | None = None
        if isinstance(profile.output_schema, dict) and profile.output_schema:
            schema_payload = dict(profile.output_schema)
            schema_resolution = "profile_inline"
        elif self.schema_registry is not None:
            loaded = self.schema_registry.get(profile.schema_ref)
            if isinstance(loaded, dict) and loaded:
                schema_payload = dict(loaded)
                schema_resolution = "registry"

        if not isinstance(schema_payload, dict) or not schema_payload:
            schema_payload = dict(self.REVISION_OUTPUT_SCHEMA)
            schema_resolution = "fallback_flat"

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
            "using_writer_schema": schema_resolution != "fallback_flat",
        }

    @staticmethod
    def _legacy_system_prompt() -> str:
        return "你是文本修订助手。根据一致性报告修复章节问题，仅输出 JSON 对象。"
