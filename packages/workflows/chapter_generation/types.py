from __future__ import annotations

from collections.abc import Callable
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
    # 编排 writer_draft 步传入的各 agent 输出快照，供 PromptPayloadAssembler「writer_agent:writer_draft」投影。
    orchestrator_raw_state: dict[str, Any] | None = None
    persist_chapter: bool = True
    # False 时仍向 LLM 传递 target_words 与字数区间提示，但不因返回正文长度未落在 ±10% 而重试/失败。
    enforce_chapter_word_count: bool = True
    request_id: str | None = None
    trace_id: str | None = None
    live_progress_callback: Callable[[dict[str, Any]], None] | None = None
    checkpoint_callback: Callable[[dict[str, Any]], None] | None = None


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
