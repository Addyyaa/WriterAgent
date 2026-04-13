"""业务工具层封装（延迟导入，降低启动耦合）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from packages.tools.chapter_tools.chapter_generation_tool import ChapterGenerationTool
    from packages.tools.character_tools.context_tool import CharacterContextTool
    from packages.tools.consistency_tools.review_tool import ConsistencyReviewTool
    from packages.tools.retrieval_tools.project_memory_tool import ProjectMemoryRetrievalTool
    from packages.tools.world_tools.context_tool import WorldContextTool

__all__ = [
    "ChapterGenerationTool",
    "CharacterContextTool",
    "ConsistencyReviewTool",
    "ProjectMemoryRetrievalTool",
    "WorldContextTool",
]


def __getattr__(name: str) -> Any:
    if name == "ChapterGenerationTool":
        from packages.tools.chapter_tools.chapter_generation_tool import ChapterGenerationTool

        return ChapterGenerationTool
    if name == "CharacterContextTool":
        from packages.tools.character_tools.context_tool import CharacterContextTool

        return CharacterContextTool
    if name == "ConsistencyReviewTool":
        from packages.tools.consistency_tools.review_tool import ConsistencyReviewTool

        return ConsistencyReviewTool
    if name == "ProjectMemoryRetrievalTool":
        from packages.tools.retrieval_tools.project_memory_tool import ProjectMemoryRetrievalTool

        return ProjectMemoryRetrievalTool
    if name == "WorldContextTool":
        from packages.tools.world_tools.context_tool import WorldContextTool

        return WorldContextTool
    raise AttributeError(name)
