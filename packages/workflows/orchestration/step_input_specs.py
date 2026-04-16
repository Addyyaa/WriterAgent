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
        context_tier="planning",
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
        context_tier="planning",
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
    # 编排全链路 writer_draft：大纲 + alignment + 检索 + chapter_memory + writer_focus / writer_context_slice / writer_evidence_pack（story_assets 为兼容别名，内容同 slice）。
    "writer_agent:writer_draft": StepInputSpec(
        role_id="writer_agent",
        include_project=True,
        include_outline=True,
        include_working_notes=True,
        dependencies=[
            StateDependencySpec(
                step_key="outline_generation",
                required=True,
                fields=["title", "content", "structure_json"],
                compact=True,
            ),
            StateDependencySpec(
                step_key="plot_alignment",
                required=True,
                fields=["chapter_goal", "core_conflict", "narcotic_arc", "climax_twist"],
                compact=True,
            ),
            StateDependencySpec(
                step_key="character_alignment",
                required=True,
                fields=["motivation_analysis", "tone_audit", "constraints"],
                compact=True,
            ),
            StateDependencySpec(
                step_key="world_alignment",
                required=True,
                fields=[
                    "world_logic_summary",
                    "hard_constraints",
                    "reusable_assets",
                    "potential_conflicts",
                ],
                compact=True,
            ),
            StateDependencySpec(
                step_key="style_alignment",
                required=True,
                fields=[
                    "style_mission",
                    "micro_constraints",
                    "rhythm_strategy",
                    "anti_drift_checks",
                    "tonal_keywords",
                ],
                compact=True,
            ),
            StateDependencySpec(
                step_key="retrieval_context",
                required=False,
                fields=[
                    "writing_context_summary",
                    "key_evidence",
                    "potential_conflicts",
                    "information_gaps",
                ],
                compact=True,
            ),
            StateDependencySpec(
                step_key="chapter_memory",
                required=False,
                fields=["items"],
                compact=False,
            ),
            StateDependencySpec(
                step_key="writer_focus",
                required=True,
                fields=["chapter_no", "relevance_excerpt", "relevance_total_chars"],
                compact=True,
            ),
            StateDependencySpec(
                step_key="writer_context_slice",
                required=True,
                fields=[
                    "chapters",
                    "characters",
                    "world_entries",
                    "timeline_events",
                    "foreshadowings",
                ],
                compact=True,
            ),
            StateDependencySpec(
                step_key="writer_evidence_pack",
                required=True,
                fields=["meta", "prev_chapter"],
                compact=True,
            ),
        ],
        retrieval=RetrievalViewSpec(
            mode="compact_items",
            max_items=12,
            max_chars_per_item=6000,
            allowed_sources=[],
        ),
    ),
    # 独立章节生成（ChapterGenerationWorkflowService）：无编排 raw_state，由服务注入合成步骤视图。
    "writer_agent:chapter_draft": StepInputSpec(
        role_id="writer_agent",
        include_project=True,
        include_outline=False,
        include_working_notes=True,
        dependencies=[
            StateDependencySpec(
                step_key="chapter_memory",
                required=True,
                fields=["items"],
                compact=False,
            ),
            StateDependencySpec(
                step_key="writer_focus",
                required=True,
                fields=["chapter_no", "relevance_excerpt", "relevance_total_chars"],
                compact=True,
            ),
            StateDependencySpec(
                step_key="writer_context_slice",
                required=True,
                fields=[
                    "chapters",
                    "characters",
                    "world_entries",
                    "timeline_events",
                    "foreshadowings",
                ],
                compact=True,
            ),
            StateDependencySpec(
                step_key="writer_evidence_pack",
                required=True,
                fields=["meta", "prev_chapter"],
                compact=True,
            ),
        ],
        retrieval=RetrievalViewSpec(
            mode="compact_items",
            max_items=12,
            max_chars_per_item=6000,
            allowed_sources=[],
        ),
    ),
    # 一致性审查 LLM：规则聚焦 + 证据包 + Assembler 检索视图（避免全量 lore 与 output_schema 重复）
    "consistency_agent:chapter_audit": StepInputSpec(
        role_id="consistency_agent",
        include_project=True,
        include_outline=False,
        include_working_notes=False,
        dependencies=[
            StateDependencySpec(
                step_key="review_contract",
                required=True,
                fields=[
                    "audit_dimensions",
                    "allowed_severities",
                    "evidence_policy",
                ],
                compact=True,
            ),
            StateDependencySpec(
                step_key="review_focus",
                required=True,
                fields=[
                    "chapter_no",
                    "focus_character_names",
                    "primary_pov_character",
                    "focus_assets",
                    "focus_world_keywords",
                    "focus_timeline_event_ids",
                    "focus_foreshadowing_ids",
                    "focus_inventory_hints",
                    "rule_issues",
                ],
                compact=True,
            ),
            StateDependencySpec(
                step_key="review_context",
                required=True,
                fields=[
                    "chapters",
                    "characters",
                    "world_entries",
                    "timeline_events",
                    "foreshadowings",
                ],
                compact=True,
            ),
            StateDependencySpec(
                step_key="review_evidence_pack",
                required=True,
                fields=[
                    "meta",
                    "characters_detail",
                    "timeline_detail",
                    "foreshadowing_detail",
                    "world_detail",
                ],
                compact=True,
            ),
            StateDependencySpec(
                step_key="chapter_draft_audit",
                required=True,
                fields=["id", "chapter_no", "title", "summary", "content"],
                compact=False,
            ),
        ],
        retrieval=RetrievalViewSpec(
            mode="compact_items",
            max_items=6,
            max_chars_per_item=400,
            allowed_sources=[],
        ),
        context_tier="strict_review",
    ),
    "writer_agent:writer_revision": StepInputSpec(
        role_id="writer_agent",
        include_project=True,
        include_outline=False,
        include_working_notes=True,
        dependencies=[
            StateDependencySpec(
                step_key="revision_chapter",
                required=True,
                fields=["title", "content", "summary", "chapter_no"],
                compact=False,
            ),
            StateDependencySpec(
                step_key="consistency_review",
                required=True,
                fields=["status", "summary", "issues"],
                compact=True,
            ),
            StateDependencySpec(
                step_key="revision_focus",
                required=True,
                fields=[
                    "chapter_no",
                    "issue_count",
                    "issue_categories",
                    "issues_signal_excerpt",
                ],
                compact=True,
            ),
            StateDependencySpec(
                step_key="revision_context_slice",
                required=True,
                fields=["issue_signals"],
                compact=True,
            ),
            StateDependencySpec(
                step_key="revision_evidence_pack",
                required=True,
                fields=["meta", "from_issues"],
                compact=True,
            ),
        ],
        retrieval=RetrievalViewSpec(
            mode="compact_items",
            max_items=10,
            max_chars_per_item=4000,
            allowed_sources=[],
        ),
        context_tier="generative",
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
