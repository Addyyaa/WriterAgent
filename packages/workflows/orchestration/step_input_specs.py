"""各 Agent 步骤的显式输入依赖与检索视图策略。"""

from __future__ import annotations

from packages.workflows.orchestration.prompt_payload_types import (
    RetrievalViewSpec,
    StateDependencySpec,
    StepInputSpec,
)

# 键规则：默认 `role_id`；同一 role 多步骤时用 `role_id:step_key`。
STEP_INPUT_SPECS: dict[str, StepInputSpec] = {
    "planner_agent": StepInputSpec(
        role_id="planner_agent",
        include_project=True,
        include_outline=False,
        include_working_notes=False,
        dependencies=[],
        retrieval=RetrievalViewSpec(mode="none"),
    ),
    "retrieval_agent": StepInputSpec(
        role_id="retrieval_agent",
        include_project=True,
        include_outline=False,
        dependencies=[
            StateDependencySpec(
                step_key="planner_bootstrap",
                required=True,
                fields=["plan_summary", "steps"],
                compact=True,
            ),
        ],
        retrieval=RetrievalViewSpec(
            mode="compact_items",
            max_items=6,
            max_chars_per_item=6000,
            allowed_sources=[],
        ),
    ),
    "plot_agent": StepInputSpec(
        role_id="plot_agent",
        include_project=True,
        include_outline=True,
        dependencies=[
            StateDependencySpec(
                step_key="outline_generation",
                required=True,
                fields=["title", "content", "structure_json"],
                compact=True,
            ),
            StateDependencySpec(
                step_key="retrieval_context",
                required=False,
                fields=["writing_context_summary", "potential_conflicts", "information_gaps"],
                compact=True,
            ),
        ],
        retrieval=RetrievalViewSpec(
            mode="summary_only",
            allowed_sources=["memory", "summary"],
        ),
    ),
    "character_agent": StepInputSpec(
        role_id="character_agent",
        include_project=True,
        include_outline=True,
        dependencies=[
            StateDependencySpec(
                step_key="outline_generation",
                required=True,
                fields=["title", "structure_json"],
                compact=True,
            ),
            StateDependencySpec(
                step_key="retrieval_context",
                required=False,
                fields=["writing_context_summary"],
                compact=True,
            ),
        ],
        retrieval=RetrievalViewSpec(
            mode="summary_only",
            allowed_sources=["memory", "summary"],
        ),
    ),
    "world_agent": StepInputSpec(
        role_id="world_agent",
        include_project=True,
        include_outline=True,
        dependencies=[
            StateDependencySpec(
                step_key="outline_generation",
                required=True,
                fields=["title", "structure_json"],
                compact=True,
            ),
            StateDependencySpec(
                step_key="retrieval_context",
                required=False,
                fields=["writing_context_summary", "key_evidence"],
                compact=True,
            ),
        ],
        retrieval=RetrievalViewSpec(
            mode="compact_items",
            max_items=5,
            max_chars_per_item=320,
            allowed_sources=["memory", "summary"],
        ),
    ),
    "style_agent": StepInputSpec(
        role_id="style_agent",
        include_project=True,
        include_outline=True,
        dependencies=[
            StateDependencySpec(
                step_key="outline_generation",
                required=True,
                fields=["title", "structure_json"],
                compact=True,
            ),
            StateDependencySpec(
                step_key="retrieval_context",
                required=False,
                fields=["writing_context_summary"],
                compact=True,
            ),
        ],
        retrieval=RetrievalViewSpec(mode="summary_only", allowed_sources=["memory", "summary"]),
    ),
    "writer_agent:persist_artifacts": StepInputSpec(
        role_id="writer_agent",
        include_project=True,
        include_outline=True,
        include_working_notes=True,
        dependencies=[
            StateDependencySpec(
                step_key="writer_revision",
                required=False,
                fields=["revised", "chapter_id", "version_id", "writer_structured", "issues_count"],
                compact=True,
            ),
            StateDependencySpec(
                step_key="writer_draft",
                required=False,
                fields=["chapter", "candidate", "writer_structured"],
                compact=True,
            ),
            StateDependencySpec(
                step_key="consistency_review",
                required=False,
                fields=["status", "summary", "issues", "score"],
                compact=True,
            ),
        ],
        retrieval=RetrievalViewSpec(mode="none"),
    ),
}
