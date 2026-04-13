from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChapterGenerationRequest:
    project_id: object
    writing_goal: str
    chapter_no: int | None = None
    target_words: int = 1200
    style_hint: str | None = None
    include_memory_top_k: int = 8
    context_token_budget: int | None = None
    temperature: float = 0.7
    chat_turns: list[dict[str, Any]] | None = None
    working_notes: list[str] | None = None
    retrieval_context: str | None = None
    persist_chapter: bool = True
    request_id: str | None = None
    trace_id: str | None = None


@dataclass(frozen=True)
class ChapterGenerationResult:
    trace_id: str
    request_id: str
    agent_run_id: str
    mock_mode: bool
    chapter: dict
    memory_ingestion: dict
    writer_structured: dict[str, Any] | None = None
    warnings: list[str] | None = None
    skill_runs: list[dict[str, Any]] | None = None
