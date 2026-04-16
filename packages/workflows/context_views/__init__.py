"""上下文视图：第二层摘要构建（Summary-first / Detail-on-demand）。"""

from __future__ import annotations

from packages.workflows.context_views.story_assets import (
    StoryAssetSummaryBudget,
    build_story_assets_from_context,
)
from packages.workflows.context_views.writer_context import (
    build_writer_context_slice,
    build_writer_evidence_pack,
    build_writer_focus,
    build_writer_relevance_blob,
)

__all__ = [
    "StoryAssetSummaryBudget",
    "build_story_assets_from_context",
    "build_writer_context_slice",
    "build_writer_evidence_pack",
    "build_writer_focus",
    "build_writer_relevance_blob",
]
