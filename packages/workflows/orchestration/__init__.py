"""编排子包：延迟导入 WritingOrchestratorService，避免与 chapter_generation 循环依赖。"""

from __future__ import annotations

from typing import Any

from packages.workflows.orchestration.types import (
    AgentProfile,
    AgentStrategy,
    EvidenceCoverageReport,
    EvidenceItem,
    PlannerNode,
    PlannerPlan,
    RetrievalRoundDecision,
    RetrievalRoundResult,
    WorkflowRunRequest,
    WorkflowRunResult,
    WorkflowStepResult,
)

__all__ = [
    "AgentProfile",
    "AgentStrategy",
    "EvidenceCoverageReport",
    "EvidenceItem",
    "PlannerNode",
    "PlannerPlan",
    "RetrievalRoundDecision",
    "RetrievalRoundResult",
    "WorkflowRunRequest",
    "WorkflowRunResult",
    "WorkflowStepResult",
    "WritingOrchestratorService",
]


def __getattr__(name: str) -> Any:
    if name == "WritingOrchestratorService":
        from packages.workflows.orchestration.service import WritingOrchestratorService

        return WritingOrchestratorService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
