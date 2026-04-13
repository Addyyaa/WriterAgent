from __future__ import annotations

import json
from dataclasses import dataclass

from packages.core.tracing import new_request_id, new_trace_id, request_context
from packages.core.utils import ensure_non_empty_string
from packages.llm.text_generation.base import TextGenerationProvider, TextGenerationRequest
from packages.storage.postgres.repositories.outline_repository import OutlineRepository
from packages.storage.postgres.repositories.project_repository import ProjectRepository


@dataclass(frozen=True)
class OutlineGenerationRequest:
    project_id: object
    writing_goal: str
    style_hint: str | None = None
    retrieval_context: str | None = None
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
    OUTLINE_INPUT_SCHEMA = {
        "type": "object",
        "required": ["project", "writing_goal", "output_schema"],
        "properties": {
            "project": {"type": "object"},
            "writing_goal": {"type": "string", "minLength": 1},
            "style_hint": {"type": ["string", "null"]},
            "retrieval_context": {"type": ["string", "null"]},
            "output_schema": {"type": "object"},
        },
        "additionalProperties": True,
    }
    OUTLINE_OUTPUT_SCHEMA = {
        "type": "object",
        "required": ["title", "content", "structure_json"],
        "properties": {
            "title": {"type": "string", "minLength": 1},
            "content": {"type": "string", "minLength": 1},
            "structure_json": {"type": "object"},
        },
        "additionalProperties": True,
    }

    def __init__(
        self,
        *,
        project_repo: ProjectRepository,
        outline_repo: OutlineRepository,
        text_provider: TextGenerationProvider,
    ) -> None:
        self.project_repo = project_repo
        self.outline_repo = outline_repo
        self.text_provider = text_provider

    def run(self, request: OutlineGenerationRequest) -> OutlineGenerationResult:
        request_id = request.request_id or new_request_id()
        trace_id = request.trace_id or new_trace_id()
        goal = ensure_non_empty_string(request.writing_goal, field_name="writing_goal")

        with request_context(request_id=request_id, trace_id=trace_id):
            project = self.project_repo.get(request.project_id)
            if project is None:
                raise RuntimeError("project 不存在")

            prompt_json = {
                "project": {
                    "id": str(project.id),
                    "title": project.title,
                    "genre": project.genre,
                    "premise": project.premise,
                },
                "writing_goal": goal,
                "style_hint": request.style_hint,
                "retrieval_context": request.retrieval_context,
                "output_schema": {
                    "title": "string",
                    "content": "markdown string",
                    "structure_json": {
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
                },
            }

            llm_result = self.text_provider.generate(
                TextGenerationRequest(
                    system_prompt=(
                        "你是剧情规划助手。只输出 JSON 对象，字段仅允许 title/content/structure_json。"
                    ),
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
                    function_description="Return outline title/content/structure_json as JSON.",
                    metadata_json={
                        "workflow": self.WORKFLOW_NAME,
                        "trace_id": trace_id,
                    },
                )
            )

            title = str(llm_result.json_data.get("title") or "未命名大纲").strip()
            content = str(llm_result.json_data.get("content") or "").strip()
            structure_json = llm_result.json_data.get("structure_json")
            if not isinstance(structure_json, dict):
                structure_json = {
                    "acts": [
                        {
                            "name": "第一幕",
                            "chapter_targets": [goal],
                            "risk_points": [],
                        }
                    ]
                }

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
