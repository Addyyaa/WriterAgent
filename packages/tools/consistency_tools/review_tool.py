from __future__ import annotations

from packages.workflows.consistency_review.service import (
    ConsistencyReviewRequest,
    ConsistencyReviewWorkflowService,
)


class ConsistencyReviewTool:
    def __init__(self, workflow_service: ConsistencyReviewWorkflowService) -> None:
        self.workflow_service = workflow_service

    def run(self, *, project_id, chapter_id, chapter_version_id: int | None = None, trace_id: str | None = None) -> dict:
        result = self.workflow_service.run(
            ConsistencyReviewRequest(
                project_id=project_id,
                chapter_id=chapter_id,
                chapter_version_id=chapter_version_id,
                trace_id=trace_id,
            )
        )
        return {
            "report_id": result.report_id,
            "status": result.status,
            "score": result.score,
            "summary": result.summary,
            "issues": result.issues,
            "recommendations": result.recommendations,
            "llm_used": result.llm_used,
            "rule_issues_count": result.rule_issues_count,
            "llm_issues_count": result.llm_issues_count,
        }
