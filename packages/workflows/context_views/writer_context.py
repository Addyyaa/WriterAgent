"""写作链：聚焦 blob、writer_focus / writer_context_slice / writer_evidence_pack（与 consistency 证据包对称）。"""

from __future__ import annotations

import json
from typing import Any


def build_writer_relevance_blob(
    writing_goal: str,
    orchestrator_raw_state: dict[str, Any] | None,
) -> str:
    """拼接写作目标与编排侧 alignment，供 load_focused 与 writer_focus 摘要。"""
    parts: list[str] = [str(writing_goal or "").strip()]
    orch = dict(orchestrator_raw_state or {})
    for key in ("plot_alignment", "character_alignment", "world_alignment", "style_alignment"):
        block = orch.get(key)
        if isinstance(block, dict):
            parts.append(json.dumps(block, ensure_ascii=False))
    return "\n".join(parts)[:12000]


def build_writer_focus(*, chapter_no: int | None, relevance_blob: str) -> dict[str, Any]:
    """进入 Assembler 的轻量焦点元数据（非全量 blob）。"""
    b = str(relevance_blob or "")
    excerpt = b[:720] + ("..." if len(b) > 720 else "")
    return {
        "chapter_no": chapter_no,
        "relevance_excerpt": excerpt,
        "relevance_total_chars": len(b),
    }


def build_writer_evidence_pack(
    story_context: Any,
    *,
    chapter_no: int | None,
) -> dict[str, Any]:
    """硬上下文片段：邻章摘要 + preview（全文由章节工具按需拉取）。"""
    prev: dict[str, Any] | None = None
    if chapter_no is not None:
        target = int(chapter_no) - 1
        if target >= 1:
            for ch in list(getattr(story_context, "chapters", None) or []):
                if not isinstance(ch, dict):
                    continue
                try:
                    cn = int(ch.get("chapter_no"))
                except (TypeError, ValueError):
                    continue
                if cn == target:
                    prev = {
                        "id": ch.get("id"),
                        "chapter_no": ch.get("chapter_no"),
                        "title": ch.get("title"),
                        "summary": ch.get("summary"),
                        "content_preview": ch.get("content_preview"),
                    }
                    break
    return {
        "meta": {"purpose": "writer_hard_context", "current_chapter_no": chapter_no},
        "prev_chapter": prev,
    }


def build_writer_context_slice(
    story_context: Any,
    *,
    chapter_no: int | None,
    summary_first: bool,
) -> dict[str, Any]:
    """与 story_assets 同形的摘要切片；供 state.writer_context_slice 与 skill 兼容。"""
    from packages.workflows.context_views.story_assets import build_story_assets_from_context

    return build_story_assets_from_context(
        story_context,
        chapter_no=chapter_no,
        summary_first=summary_first,
    )
