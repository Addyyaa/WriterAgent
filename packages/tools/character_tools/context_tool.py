from __future__ import annotations

from packages.workflows.chapter_generation.context_provider import SQLAlchemyStoryContextProvider


class CharacterContextTool:
    def __init__(self, context_provider: SQLAlchemyStoryContextProvider) -> None:
        self.context_provider = context_provider

    def run(self, *, project_id, top_k: int = 20) -> dict:
        ctx = self.context_provider.load(project_id=project_id)
        items = list(ctx.characters)[: max(1, int(top_k))]
        return {
            "count": len(items),
            "items": items,
        }
