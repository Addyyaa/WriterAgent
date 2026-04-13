from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

from packages.workflows.orchestration.runtime_config import PlannerRuntimeConfig
from packages.workflows.orchestration.types import PlannerNode, PlannerPlan, WorkflowRunRequest


_DEFAULT_PLANNER_PROMPT = (
    "你是写作工作流规划器。输出 JSON：{nodes:[...], retry_policy:{}, fallback_policy:{}}。"
)
_PLANNER_JSON_CONTRACT = (
    "你必须仅输出一个 JSON 对象，不要输出 markdown，不要输出解释文字。"
)


class DynamicPlanner:
    def plan(self, request: WorkflowRunRequest, *, context_json: dict[str, Any]) -> PlannerPlan:
        raise NotImplementedError


class MockDynamicPlanner(DynamicPlanner):
    """确定性动态规划器（默认）。"""

    def plan(self, request: WorkflowRunRequest, *, context_json: dict[str, Any]) -> PlannerPlan:
        workflow = (request.workflow_type or "writing_full").strip().lower()
        if workflow in {"outline_generation", "chapter_generation", "consistency_review", "revision"}:
            return PlannerPlan(
                plan_version="mock-v1",
                nodes=[
                    PlannerNode(
                        step_key=workflow,
                        step_type="workflow",
                        workflow_type=workflow,
                        agent_name=_default_agent_for(workflow),
                        input_json={},
                    )
                ],
                retry_policy={"max_retries": 1},
                fallback_policy={"mode": "none"},
            )

        nodes = [
            PlannerNode(
                step_key="planner_bootstrap",
                step_type="agent",
                workflow_type="planner",
                agent_name="planner_agent",
                role_id="planner_agent",
                input_json={"goal": request.writing_goal},
            ),
            PlannerNode(
                step_key="retrieval_context",
                step_type="agent",
                workflow_type="retrieval_context",
                agent_name="retrieval_agent",
                role_id="retrieval_agent",
                depends_on=["planner_bootstrap"],
            ),
            PlannerNode(
                step_key="outline_generation",
                step_type="workflow",
                workflow_type="outline_generation",
                agent_name="plot_agent",
                role_id="plot_agent",
                depends_on=["retrieval_context"],
            ),
            PlannerNode(
                step_key="plot_alignment",
                step_type="agent",
                workflow_type="plot_alignment",
                agent_name="plot_agent",
                role_id="plot_agent",
                depends_on=["outline_generation"],
            ),
            PlannerNode(
                step_key="character_alignment",
                step_type="agent",
                workflow_type="character_alignment",
                agent_name="character_agent",
                role_id="character_agent",
                depends_on=["outline_generation"],
            ),
            PlannerNode(
                step_key="world_alignment",
                step_type="agent",
                workflow_type="world_alignment",
                agent_name="world_agent",
                role_id="world_agent",
                depends_on=["outline_generation"],
            ),
            PlannerNode(
                step_key="style_alignment",
                step_type="agent",
                workflow_type="style_alignment",
                agent_name="style_agent",
                role_id="style_agent",
                depends_on=["outline_generation"],
            ),
            PlannerNode(
                step_key="writer_draft",
                step_type="workflow",
                workflow_type="chapter_generation",
                agent_name="writer_agent",
                role_id="writer_agent",
                strategy_mode="draft",
                depends_on=[
                    "plot_alignment",
                    "character_alignment",
                    "world_alignment",
                    "style_alignment",
                ],
            ),
            PlannerNode(
                step_key="consistency_review",
                step_type="workflow",
                workflow_type="consistency_review",
                agent_name="consistency_agent",
                role_id="consistency_agent",
                depends_on=["writer_draft"],
            ),
            PlannerNode(
                step_key="writer_revision",
                step_type="workflow",
                workflow_type="revision",
                agent_name="writer_agent",
                role_id="writer_agent",
                strategy_mode="revision",
                depends_on=["consistency_review"],
            ),
            PlannerNode(
                step_key="persist_artifacts",
                step_type="agent",
                workflow_type="persist_artifacts",
                agent_name="writer_agent",
                role_id="writer_agent",
                depends_on=["writer_revision"],
            ),
        ]
        return PlannerPlan(
            plan_version="mock-v1",
            nodes=nodes,
            retry_policy={"max_retries": 2, "retry_delay_seconds": 30},
            fallback_policy={"revision_on_warning": True, "revision_on_failed": True},
        )


class OpenAICompatibleDynamicPlanner(DynamicPlanner):
    def __init__(
        self,
        config: PlannerRuntimeConfig,
        fallback: DynamicPlanner | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self.config = config
        self.fallback = fallback or MockDynamicPlanner()
        self.system_prompt = _build_planner_system_prompt(system_prompt)

    def plan(self, request: WorkflowRunRequest, *, context_json: dict[str, Any]) -> PlannerPlan:
        if self.config.use_mock:
            return self.fallback.plan(request, context_json=context_json)

        payload = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": self.system_prompt,
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "workflow_type": request.workflow_type,
                            "writing_goal": request.writing_goal,
                            "context": context_json,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": self.config.temperature,
            "response_format": {"type": "json_object"},
        }

        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        try:
            resp = httpx.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.config.timeout_seconds,
            )
            body = resp.json()
            if resp.status_code >= 400:
                raise RuntimeError(f"planner 请求失败 status={resp.status_code}: {body}")
            content = body["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            nodes = []
            for item in parsed.get("nodes", []):
                if not isinstance(item, dict):
                    continue
                nodes.append(
                    PlannerNode(
                        step_key=str(item.get("step_key") or ""),
                        step_type=str(item.get("step_type") or "workflow"),
                        workflow_type=str(item.get("workflow_type") or "chapter_generation"),
                        agent_name=str(item.get("agent_name") or "writer_agent"),
                        role_id=str(item.get("role_id") or item.get("agent_name") or "writer_agent"),
                        strategy_mode=(
                            str(item.get("strategy_mode")).strip() if item.get("strategy_mode") is not None else None
                        ),
                        depends_on=[str(x) for x in list(item.get("depends_on") or [])],
                        input_json=dict(item.get("input_json") or {}),
                    )
                )
            if not nodes:
                return self.fallback.plan(request, context_json=context_json)
            return PlannerPlan(
                plan_version="llm-v1",
                nodes=nodes,
                retry_policy=dict(parsed.get("retry_policy") or {}),
                fallback_policy=dict(parsed.get("fallback_policy") or {}),
            )
        except Exception:
            if self.config.fallback_to_mock_on_error:
                return self.fallback.plan(request, context_json=context_json)
            raise


def create_dynamic_planner(config: PlannerRuntimeConfig | None = None) -> DynamicPlanner:
    cfg = config or PlannerRuntimeConfig.from_env()
    return OpenAICompatibleDynamicPlanner(config=cfg, fallback=MockDynamicPlanner())


def _build_planner_system_prompt(override_prompt: str | None = None) -> str:
    base = (override_prompt or "").strip()
    if not base:
        loaded = _load_prompt_from_agent_profile()
        base = loaded or _DEFAULT_PLANNER_PROMPT
    return f"{base}\n{_PLANNER_JSON_CONTRACT}"


def _load_prompt_from_agent_profile() -> str | None:
    root_raw = os.environ.get("WRITER_AGENT_CONFIG_ROOT", "apps/agents").strip() or "apps/agents"
    root = Path(root_raw).expanduser()
    if not root.is_absolute():
        root = (Path.cwd() / root).resolve()

    prompt_path = root / "planner_agent" / "prompt.md"
    if not prompt_path.exists():
        return None

    content = prompt_path.read_text(encoding="utf-8").strip()
    return content or None


def _default_agent_for(workflow: str) -> str:
    mapping = {
        "outline_generation": "plot_agent",
        "chapter_generation": "writer_agent",
        "consistency_review": "consistency_agent",
        "revision": "writer_agent",
    }
    return mapping.get(workflow, "writer_agent")
