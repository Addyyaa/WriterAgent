"""上下文视图：第二层摘要构建（Summary-first / Detail-on-demand）。"""

from __future__ import annotations

from packages.workflows.context_views.story_assets import (
    StoryAssetSummaryBudget,
    build_story_assets_from_context,
)

__all__ = [
    "StoryAssetSummaryBudget",
    "build_story_assets_from_context",
]
