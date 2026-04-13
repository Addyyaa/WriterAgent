from __future__ import annotations

from packages.memory.project_memory.project_memory_service import ProjectMemoryService


class ProjectMemoryRetrievalTool:
    def __init__(self, project_memory_service: ProjectMemoryService) -> None:
        self.project_memory_service = project_memory_service

    def run(
        self,
        *,
        project_id,
        query: str,
        top_k: int = 8,
        token_budget: int = 1800,
    ) -> dict:
        ctx = self.project_memory_service.build_context(
            project_id=project_id,
            query=query,
            top_k=top_k,
            token_budget=token_budget,
        )
        return {
            "query": query,
            "used_tokens": int(ctx.used_tokens),
            "truncated": bool(ctx.truncated),
            "items": [
                {
                    "source": item.source,
                    "text": item.text,
                    "priority": float(item.priority),
                    "metadata": dict(item.metadata or {}),
                }
                for item in ctx.items
            ],
        }
