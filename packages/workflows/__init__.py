"""跨模块 workflow 编排入口（延迟导入，避免循环依赖）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from packages.workflows.chapter_generation.service import ChapterGenerationWorkflowService
    from packages.workflows.consistency_review.service import ConsistencyReviewWorkflowService
    from packages.workflows.orchestration.service import WritingOrchestratorService
    from packages.workflows.outline_generation.service import OutlineGenerationWorkflowService
    from packages.workflows.revision.service import RevisionWorkflowService

__all__ = [
    "ChapterGenerationWorkflowService",
    "ConsistencyReviewWorkflowService",
    "OutlineGenerationWorkflowService",
    "RevisionWorkflowService",
    "WritingOrchestratorService",
]


def __getattr__(name: str) -> Any:
    if name == "ChapterGenerationWorkflowService":
        from packages.workflows.chapter_generation.service import ChapterGenerationWorkflowService

        return ChapterGenerationWorkflowService
    if name == "ConsistencyReviewWorkflowService":
        from packages.workflows.consistency_review.service import ConsistencyReviewWorkflowService

        return ConsistencyReviewWorkflowService
    if name == "OutlineGenerationWorkflowService":
        from packages.workflows.outline_generation.service import OutlineGenerationWorkflowService

        return OutlineGenerationWorkflowService
    if name == "RevisionWorkflowService":
        from packages.workflows.revision.service import RevisionWorkflowService

        return RevisionWorkflowService
    if name == "WritingOrchestratorService":
        from packages.workflows.orchestration.service import WritingOrchestratorService

        return WritingOrchestratorService
    raise AttributeError(name)
