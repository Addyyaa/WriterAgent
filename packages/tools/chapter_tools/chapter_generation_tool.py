from __future__ import annotations

from packages.workflows.chapter_generation.service import ChapterGenerationWorkflowService
from packages.workflows.chapter_generation.types import (
    ChapterGenerationRequest,
    ChapterGenerationResult,
)


class ChapterGenerationTool:
    """供 agent/orchestrator 调用的章节生成工具包装。"""

    def __init__(self, workflow_service: ChapterGenerationWorkflowService) -> None:
        self.workflow_service = workflow_service

    def run(self, request: ChapterGenerationRequest) -> ChapterGenerationResult:
        return self.workflow_service.run(request)
