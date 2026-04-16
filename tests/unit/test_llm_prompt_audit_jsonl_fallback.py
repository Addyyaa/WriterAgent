"""LLM 审计 JSONL 兜底读取（与 DB 无行时的管理员查询对齐）。"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from packages.llm.prompt_audit.record import (
    normalize_llm_prompt_audit_row,
    read_llm_prompt_audit_from_jsonl,
)


def test_read_llm_prompt_audit_from_jsonl_last_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tid = uuid.uuid4()
    path = tmp_path / "llm_prompt_audit.jsonl"
    line_old = json.dumps({"id": str(tid), "model": "old"}, ensure_ascii=False)
    line_new = json.dumps(
        {"id": str(tid), "model": "new", "system_prompt": "s", "user_prompt": "u"},
        ensure_ascii=False,
    )
    path.write_text(line_old + "\n" + line_new + "\n", encoding="utf-8")

    monkeypatch.setattr(
        "packages.llm.prompt_audit.record._jsonl_fallback_path",
        lambda: path,
    )
    row = read_llm_prompt_audit_from_jsonl(tid)
    assert row is not None
    assert row["model"] == "new"


def test_normalize_llm_prompt_audit_row_adds_created_at() -> None:
    n = normalize_llm_prompt_audit_row({"id": "550e8400-e29b-41d4-a716-446655440000"})
    assert n["created_at"] is None
    assert n["id"] == "550e8400-e29b-41d4-a716-446655440000"
