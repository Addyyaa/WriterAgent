"""修订链：由 consistency issues 生成 revision_focus / slice / evidence_pack（summary-first，与 writer/consistency 证据包对称）。"""

from __future__ import annotations

from typing import Any


def build_revision_focus(*, chapter_no: int | None, issues: list[dict[str, Any]]) -> dict[str, Any]:
    """轻量焦点：类别与 issues 信号摘录，供 Assembler 与模型先读。"""
    categories: list[str] = []
    for item in issues:
        if not isinstance(item, dict):
            continue
        c = str(item.get("category") or "").strip()
        if c and c not in categories:
            categories.append(c)
    blob_parts: list[str] = []
    for item in issues[:12]:
        if not isinstance(item, dict):
            continue
        hint = str(item.get("revision_suggestion") or item.get("reasoning") or "").strip()
        if hint:
            blob_parts.append(hint[:400])
    joined = " | ".join(blob_parts)
    excerpt = joined[:720] + ("..." if len(joined) > 720 else "")
    return {
        "chapter_no": chapter_no,
        "issue_count": len(issues),
        "issue_categories": categories[:12],
        "issues_signal_excerpt": excerpt,
    }


def build_revision_context_slice(*, issues: list[dict[str, Any]]) -> dict[str, Any]:
    """issues 的摘要信号列表，避免重复塞满条全文。"""
    signals: list[dict[str, Any]] = []
    for item in issues[:24]:
        if not isinstance(item, dict):
            continue
        signals.append(
            {
                "category": item.get("category"),
                "severity": item.get("severity"),
                "reasoning_summary": str(item.get("reasoning") or "")[:320],
            }
        )
    return {"issue_signals": signals}


def build_revision_evidence_pack(*, issues: list[dict[str, Any]]) -> dict[str, Any]:
    """逐条 issue 的短证据字段，供对照原文修订。"""
    entries: list[dict[str, Any]] = []
    for idx, item in enumerate(issues[:16]):
        if not isinstance(item, dict):
            continue
        entries.append(
            {
                "issue_index": idx,
                "evidence_context": str(item.get("evidence_context") or "")[:1200],
                "evidence_draft": str(item.get("evidence_draft") or "")[:1200],
                "revision_suggestion": str(item.get("revision_suggestion") or "")[:1200],
            }
        )
    return {
        "meta": {"purpose": "revision_issue_evidence", "issue_count": len(issues)},
        "from_issues": entries,
    }
