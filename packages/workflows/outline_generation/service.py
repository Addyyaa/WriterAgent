from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packages.core.tracing import new_request_id, new_trace_id, request_context
from packages.core.utils import ensure_non_empty_string
from packages.llm.text_generation.base import TextGenerationProvider, TextGenerationRequest
from packages.memory.project_memory.project_memory_service import ProjectMemoryService
from packages.storage.postgres.repositories.outline_repository import OutlineRepository
from packages.storage.postgres.repositories.project_repository import ProjectRepository

logger = logging.getLogger(__name__)

# packages/workflows/outline_generation/service.py → 仓库根为 parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUTLINE_SYSTEM_PROMPT_PATH = _REPO_ROOT / "apps" / "agents" / "outline_generation" / "prompt_system.md"

_OUTLINE_ACT_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "chapter_targets", "risk_points"],
    "properties": {
        "name": {"type": "string"},
        "chapter_targets": {"type": "array", "items": {"type": "string"}},
        "risk_points": {"type": "array", "items": {"type": "string"}},
    },
}

_OUTLINE_STRUCTURE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "chapter_goal",
        "core_conflict",
        "end_hook",
        "must_preserve_facts",
        "open_questions",
        "assumptions_used",
        "acts",
        "character_arcs",
        "foreshadowing_plan",
    ],
    "properties": {
        "chapter_goal": {"type": "string"},
        "core_conflict": {"type": "string"},
        "end_hook": {"type": "string"},
        "must_preserve_facts": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "assumptions_used": {"type": "array", "items": {"type": "string"}},
        "acts": {"type": "array", "items": _OUTLINE_ACT_ITEM_SCHEMA},
        "character_arcs": {"type": "array", "items": {"type": "string"}},
        "foreshadowing_plan": {"type": "array", "items": {"type": "string"}},
    },
}

_OUTLINE_PROJECT_BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": True,
    "required": ["id", "premise", "metadata_json"],
    "properties": {
        "id": {"type": "string"},
        "title": {"type": ["string", "null"]},
        "genre": {"type": ["string", "null"]},
        "premise": {"type": "string"},
        "metadata_json": {"type": "object", "additionalProperties": True},
    },
}

_PRIOR_CHAPTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["chapter_no", "title", "summary"],
    "properties": {
        "chapter_no": {"type": "integer"},
        "title": {"type": ["string", "null"]},
        "summary": {"type": ["string", "null"]},
    },
}

_OUTLINE_INTAKE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "project_brief",
        "target_chapter_position",
        "prior_chapter_summary",
        "confirmed_facts",
        "current_states",
        "supporting_evidence",
        "conflicts",
        "information_gaps",
        "key_facts",
    ],
    "properties": {
        "project_brief": _OUTLINE_PROJECT_BRIEF_SCHEMA,
        "target_chapter_position": {
            "type": "object",
            "additionalProperties": True,
            "required": ["chapter_no", "target_words", "arc_stage", "next_hook_type"],
            "properties": {
                "chapter_no": {"type": ["integer", "null"]},
                "target_words": {"type": ["integer", "null"]},
                "arc_stage": {"type": ["string", "null"]},
                "next_hook_type": {"type": ["string", "null"]},
            },
        },
        "prior_chapter_summary": {
            "anyOf": [_PRIOR_CHAPTER_SCHEMA, {"type": "null"}],
        },
        "confirmed_facts": {"type": "array", "items": {"type": "string"}},
        "current_states": {"type": "array", "items": {"type": "string"}},
        "supporting_evidence": {"type": "array", "items": {"type": "string"}},
        "conflicts": {"type": "array", "items": {"type": "string"}},
        "information_gaps": {"type": "array", "items": {"type": "string"}},
        "key_facts": {"type": "array", "items": {"type": "string"}},
    },
}


def _load_outline_system_prompt() -> str:
    try:
        raw = _OUTLINE_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        if raw.strip():
            return raw.strip()
    except OSError:
        pass
    return (
        "你是大纲生成代理。只输出 JSON，字段仅允许 title/content/structure_json。"
        "content 仅为章节梗概（outline synopsis），禁止正文与完整对话。"
    )


def _fallback_structure_json(goal: str) -> dict[str, Any]:
    return {
        "chapter_goal": goal,
        "core_conflict": "",
        "end_hook": "",
        "must_preserve_facts": [],
        "open_questions": [],
        "assumptions_used": [],
        "acts": [
            {
                "name": "第一幕",
                "chapter_targets": [goal],
                "risk_points": [],
            }
        ],
        "character_arcs": [],
        "foreshadowing_plan": [],
    }


def _coerce_structure_json(raw: Any, goal: str) -> tuple[dict[str, Any], bool]:
    """补齐 structure_json 缺字段；返回 (dict, 是否发生过补齐)。"""
    coerced = False
    if not isinstance(raw, dict):
        return _fallback_structure_json(goal), True

    out = dict(raw)
    defaults: dict[str, Any] = {
        "chapter_goal": "",
        "core_conflict": "",
        "end_hook": "",
        "must_preserve_facts": [],
        "open_questions": [],
        "assumptions_used": [],
        "character_arcs": [],
        "foreshadowing_plan": [],
    }
    for key, default in defaults.items():
        if key not in out:
            out[key] = default
            coerced = True
        elif key in (
            "must_preserve_facts",
            "open_questions",
            "assumptions_used",
            "character_arcs",
            "foreshadowing_plan",
        ) and not isinstance(out.get(key), list):
            out[key] = list(default) if isinstance(default, list) else default
            coerced = True
        elif key in ("chapter_goal", "core_conflict", "end_hook") and not isinstance(
            out.get(key), str
        ):
            out[key] = str(out.get(key) or "")
            coerced = True

    acts = out.get("acts")
    if not isinstance(acts, list) or not acts:
        out["acts"] = [
            {
                "name": "第一幕",
                "chapter_targets": [goal],
                "risk_points": [],
            }
        ]
        coerced = True
    else:
        normalized_acts: list[dict[str, Any]] = []
        for a in acts:
            if not isinstance(a, dict):
                coerced = True
                continue
            name = str(a.get("name") or "").strip() or "幕"
            ct = a.get("chapter_targets")
            if not isinstance(ct, list):
                ct = [goal]
                coerced = True
            rp = a.get("risk_points")
            if not isinstance(rp, list):
                rp = []
                coerced = True
            normalized_acts.append(
                {
                    "name": name,
                    "chapter_targets": [str(x) for x in ct],
                    "risk_points": [str(x) for x in rp],
                }
            )
        if not normalized_acts:
            out["acts"] = _fallback_structure_json(goal)["acts"]
            coerced = True
        else:
            out["acts"] = normalized_acts

    if not str(out.get("chapter_goal") or "").strip():
        out["chapter_goal"] = goal
        coerced = True

    return out, coerced


@dataclass(frozen=True)
class OutlineGenerationRequest:
    project_id: object
    writing_goal: str
    outline_intake: dict[str, Any]
    style_hint: str | None = None
    request_id: str | None = None
    trace_id: str | None = None


@dataclass(frozen=True)
class OutlineGenerationResult:
    request_id: str
    trace_id: str
    outline_id: str
    version_no: int
    title: str | None
    content: str | None
    structure_json: dict
    mock_mode: bool


class OutlineGenerationWorkflowService:
    AGENT_NAME = "plot_agent"
    WORKFLOW_NAME = "outline_generation"
    OUTLINE_INPUT_SCHEMA: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["writing_goal", "style_hint", "outline_intake", "output_schema"],
        "properties": {
            "writing_goal": {"type": "string", "minLength": 1},
            "style_hint": {"type": ["string", "null"]},
            "outline_intake": _OUTLINE_INTAKE_SCHEMA,
            "output_schema": {"type": "object"},
        },
    }
    OUTLINE_OUTPUT_SCHEMA: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["title", "content", "structure_json"],
        "properties": {
            "title": {"type": "string", "minLength": 1},
            "content": {
                "type": "string",
                "minLength": 1,
                "maxLength": 4000,
                "description": "outline synopsis only; no full prose or dialogue",
            },
            "structure_json": _OUTLINE_STRUCTURE_JSON_SCHEMA,
        },
    }

    def __init__(
        self,
        *,
        project_repo: ProjectRepository,
        outline_repo: OutlineRepository,
        text_provider: TextGenerationProvider,
        project_memory_service: ProjectMemoryService | None = None,
    ) -> None:
        self.project_repo = project_repo
        self.outline_repo = outline_repo
        self.text_provider = text_provider
        self.project_memory_service = project_memory_service

    def _local_data_tool_llm_fields(self) -> dict[str, Any]:
        """大纲生成与 agent 步一致：FC 挂载本地数据查询（依赖 project_memory_service）。"""
        from packages.tools.system_tools.local_data_tools_dispatch import (
            LOCAL_DATA_TOOLS_OPENAI,
            execute_local_data_tool,
        )

        pms = self.project_memory_service
        if pms is None:
            return {}
        db = self.project_repo.db

        def _run(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            return execute_local_data_tool(
                name=name,
                arguments=arguments,
                db=db,
                project_memory_service=pms,
            )

        return {
            "extra_function_tools": tuple(LOCAL_DATA_TOOLS_OPENAI),
            "local_data_tool_executor": _run,
            "local_data_tool_max_rounds": 8,
        }

    def run(self, request: OutlineGenerationRequest) -> OutlineGenerationResult:
        request_id = request.request_id or new_request_id()
        trace_id = request.trace_id or new_trace_id()
        goal = ensure_non_empty_string(request.writing_goal, field_name="writing_goal")

        with request_context(request_id=request_id, trace_id=trace_id):
            project = self.project_repo.get(request.project_id)
            if project is None:
                raise RuntimeError("project 不存在")

            output_schema_hint = {
                "title": "string",
                "content": (
                    "outline synopsis（章节事件梗概+推进理由+章末钩子；"
                    "禁止正文描写、完整对话、连续 prose）"
                ),
                "structure_json": {
                    "chapter_goal": "string",
                    "core_conflict": "string",
                    "end_hook": "string",
                    "must_preserve_facts": ["string"],
                    "open_questions": ["string"],
                    "assumptions_used": ["string"],
                    "acts": [
                        {
                            "name": "string",
                            "chapter_targets": ["string"],
                            "risk_points": ["string"],
                        }
                    ],
                    "character_arcs": ["string"],
                    "foreshadowing_plan": ["string"],
                },
            }

            intake = request.outline_intake
            if not isinstance(intake, dict):
                raise ValueError("outline_intake 必须为 object")

            prompt_json: dict[str, Any] = {
                "writing_goal": goal,
                "style_hint": request.style_hint,
                "outline_intake": intake,
                "output_schema": output_schema_hint,
            }

            llm_result = self.text_provider.generate(
                TextGenerationRequest(
                    system_prompt=_load_outline_system_prompt(),
                    user_prompt=json.dumps(prompt_json, ensure_ascii=False),
                    temperature=0.6,
                    input_payload=prompt_json,
                    input_schema=self.OUTLINE_INPUT_SCHEMA,
                    input_schema_name="outline_generation_input",
                    input_schema_strict=True,
                    response_schema=self.OUTLINE_OUTPUT_SCHEMA,
                    response_schema_name="outline_generation_output",
                    response_schema_strict=True,
                    validation_retries=2,
                    use_function_calling=True,
                    function_name="outline_generation_output",
                    function_description=(
                        "Return outline title, outline synopsis content, and structure_json."
                    ),
                    metadata_json={
                        "workflow": self.WORKFLOW_NAME,
                        "trace_id": trace_id,
                    },
                    **self._local_data_tool_llm_fields(),
                )
            )

            title = str(llm_result.json_data.get("title") or "未命名大纲").strip()
            content = str(llm_result.json_data.get("content") or "").strip()
            structure_json, coerced = _coerce_structure_json(
                llm_result.json_data.get("structure_json"), goal
            )
            if coerced:
                logger.info(
                    json.dumps(
                        {
                            "event": "outline_structure_json_coerced",
                            "trace_id": trace_id,
                            "project_id": str(request.project_id),
                        },
                        ensure_ascii=False,
                    )
                )

            row = self.outline_repo.create_version(
                project_id=request.project_id,
                title=title,
                content=content,
                structure_json=structure_json,
                source_agent=self.AGENT_NAME,
                source_workflow=self.WORKFLOW_NAME,
                trace_id=trace_id,
                set_active=True,
            )

            return OutlineGenerationResult(
                request_id=request_id,
                trace_id=trace_id,
                outline_id=str(row.id),
                version_no=int(row.version_no),
                title=row.title,
                content=row.content,
                structure_json=dict(row.structure_json or {}),
                mock_mode=bool(llm_result.is_mock),
            )
