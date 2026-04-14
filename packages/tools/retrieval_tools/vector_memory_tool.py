from __future__ import annotations

from typing import Any

from packages.memory.project_memory.project_memory_service import ProjectMemoryService


class ProjectVectorMemorySearchTool:
    """通过项目长期记忆（向量 + 混合检索管线）查询相关内容。"""

    def __init__(self, project_memory_service: ProjectMemoryService) -> None:
        self._service = project_memory_service

    def run(
        self,
        *,
        project_id,
        query: str,
        top_k: int = 8,
        token_budget: int = 2000,
        source_type: str | None = None,
        chunk_type: str | None = None,
    ) -> dict[str, Any]:
        ctx = self._service.build_context(
            project_id=project_id,
            query=str(query or "").strip(),
            top_k=max(1, min(int(top_k), 64)),
            token_budget=max(200, int(token_budget)),
            source_type=source_type,
            chunk_type=chunk_type,
        )
        return {
            "query": str(query or "").strip(),
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
