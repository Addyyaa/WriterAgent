from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentStrategy:
    version: str
    temperature: float
    max_tokens: int
    style: str = "default"
    mode: str = "default"
    mode_strategies: dict[str, dict[str, Any]] = field(default_factory=dict)

    def resolve_mode(self, mode: str | None) -> "AgentStrategy":
        target = str(mode or self.mode or "default").strip().lower()
        override = dict(self.mode_strategies.get(target) or {})
        if not override:
            return AgentStrategy(
                version=self.version,
                temperature=float(self.temperature),
                max_tokens=int(self.max_tokens),
                style=self.style,
                mode=target,
                mode_strategies=dict(self.mode_strategies),
            )
        return AgentStrategy(
            version=self.version,
            temperature=float(override.get("temperature", self.temperature)),
            max_tokens=int(override.get("max_tokens", self.max_tokens)),
            style=str(override.get("style", self.style)),
            mode=target,
            mode_strategies=dict(self.mode_strategies),
        )


@dataclass(frozen=True)
class AgentProfile:
    role_id: str
    prompt: str
    strategy: AgentStrategy
    skills: list[str] = field(default_factory=list)
    skill_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    schema_ref: str = "agents/agent_step_output.schema.json"
    schema_version: str = "v1"
    output_schema: dict[str, Any] | None = None
    consumption_contract: dict[str, str] = field(default_factory=dict)
    consumption_warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WorkflowRunRequest:
    project_id: object
    writing_goal: str
    workflow_type: str = "writing_full"
    chapter_no: int | None = None
    target_words: int = 1200
    style_hint: str | None = None
    include_memory_top_k: int = 8
    context_token_budget: int | None = None
    temperature: float = 0.7
    chat_turns: list[dict[str, Any]] | None = None
    working_notes: list[str] | None = None
    session_id: str | None = None
    user_id: str | None = None
    request_id: str | None = None
    trace_id: str | None = None
    idempotency_key: str | None = None
    metadata_json: dict[str, Any] = field(default_factory=dict)
    enforce_chapter_word_count: bool = True


@dataclass(frozen=True)
class WorkflowRunResult:
    run_id: str
    status: str
    trace_id: str
    request_id: str


@dataclass(frozen=True)
class PlannerNode:
    step_key: str
    step_type: str
    workflow_type: str
    agent_name: str
    role_id: str | None = None
    strategy_mode: str | None = None
    depends_on: list[str] = field(default_factory=list)
    input_json: dict[str, Any] = field(default_factory=dict)
    # 信息需求（与 planner_bootstrap JSON 语义对齐；动态规划器 nodes[] 一级字段）
    required_slots: list[str] = field(default_factory=list)
    preferred_tools: list[str] = field(default_factory=list)
    must_verify_facts: list[str] = field(default_factory=list)
    allowed_assumptions: list[str] = field(default_factory=list)
    fallback_when_missing: str | None = None


@dataclass(frozen=True)
class PlannerPlan:
    plan_version: str
    nodes: list[PlannerNode]
    retry_policy: dict[str, Any] = field(default_factory=dict)
    fallback_policy: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowStepResult:
    step_key: str
    status: str
    output_json: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    retrieval_trace_id: str | None = None
    strategy_mode: str | None = None
    context_budget_usage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalRoundDecision:
    query: str
    intent: str
    source_types: list[str] = field(default_factory=list)
    time_scope: dict[str, Any] = field(default_factory=dict)
    chapter_window: dict[str, int] = field(default_factory=dict)
    must_have_slots: list[str] = field(default_factory=list)
    enough_context: bool = False
    # 每开放槽位对应的检索短语（回放审计）
    slot_query_fragments: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceItem:
    source_type: str
    text: str
    source_id: str | None = None
    chunk_id: str | None = None
    score: float | None = None
    adopted: bool = True
    metadata_json: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceCoverageReport:
    coverage_score: float
    resolved_slots: list[str] = field(default_factory=list)
    open_slots: list[str] = field(default_factory=list)
    enough_context: bool = False
    stop_reason: str | None = None


@dataclass(frozen=True)
class RetrievalRoundResult:
    round_index: int
    decision: RetrievalRoundDecision
    coverage: EvidenceCoverageReport
    evidence_items: list[EvidenceItem] = field(default_factory=list)
    new_evidence_gain: float = 0.0
    latency_ms: int | None = None
