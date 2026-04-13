from __future__ import annotations

import re
from typing import Any


class WriterOutputAdapterError(RuntimeError):
    """Writer 输出适配失败。"""


WRITER_OUTPUT_V2_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["mode", "status", "segments", "word_count", "chapter"],
    "properties": {
        "mode": {"type": "string", "enum": ["draft", "revision"]},
        "status": {"type": "string", "enum": ["success", "failed"]},
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["beat_id", "content"],
                "properties": {
                    "beat_id": {"type": "integer"},
                    "type": {
                        "type": "string",
                        "enum": ["action", "dialogue", "description", "internal_monologue"],
                    },
                    "content": {"type": "string", "minLength": 1},
                },
                "additionalProperties": True,
            },
        },
        "word_count": {"type": "integer", "minimum": 0},
        "notes": {"type": "string"},
        "chapter": {
            "type": "object",
            "required": ["title", "content", "summary"],
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "content": {"type": "string", "minLength": 1},
                "summary": {"type": "string", "minLength": 1},
            },
            "additionalProperties": True,
        },
    },
    "additionalProperties": True,
}


class WriterOutputAdapter:
    """将 writer 输出归一化为可消费的 WriterOutputV2。"""

    _SEGMENT_TYPES = {"action", "dialogue", "description", "internal_monologue"}

    @classmethod
    def normalize(cls, payload: dict[str, Any] | None, *, mode: str) -> dict[str, Any]:
        raw = dict(payload or {})
        normalized_mode = cls._normalize_mode(raw.get("mode"), fallback=mode)
        status = cls._normalize_status(raw.get("status"))
        segments = cls._normalize_segments(raw.get("segments"))
        chapter = cls._normalize_chapter(raw=raw, segments=segments)
        if not str(chapter.get("content") or "").strip():
            raise WriterOutputAdapterError("writer 输出缺少 chapter.content，且无法从 segments 回填")

        notes = str(raw.get("notes") or "").strip()
        raw_word_count = raw.get("word_count")
        if isinstance(raw_word_count, int) and raw_word_count >= 0:
            word_count = int(raw_word_count)
        else:
            word_count = cls._estimate_word_count(str(chapter.get("content") or ""))

        return {
            "mode": normalized_mode,
            "status": status,
            "segments": segments,
            "word_count": int(word_count),
            "notes": notes,
            "chapter": chapter,
        }

    @classmethod
    def legacy_chapter(cls, writer_output: dict[str, Any]) -> dict[str, str]:
        chapter = dict(writer_output.get("chapter") or {})
        title = str(chapter.get("title") or "").strip()
        content = str(chapter.get("content") or "").strip()
        summary = str(chapter.get("summary") or "").strip()
        if not content:
            raise WriterOutputAdapterError("writer_structured 缺少 chapter.content")
        return {
            "title": title or "未命名章节",
            "content": content,
            "summary": summary or cls._auto_summary(content),
        }

    @classmethod
    def _normalize_segments(cls, raw_segments: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_segments, list):
            return []
        out: list[dict[str, Any]] = []
        for idx, item in enumerate(raw_segments, start=1):
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            beat_id = item.get("beat_id")
            try:
                normalized_beat_id = int(beat_id)
            except (TypeError, ValueError):
                normalized_beat_id = idx
            seg_type = str(item.get("type") or "description").strip().lower()
            if seg_type not in cls._SEGMENT_TYPES:
                seg_type = "description"
            out.append(
                {
                    "beat_id": normalized_beat_id,
                    "type": seg_type,
                    "content": content,
                }
            )
        return out

    @classmethod
    def _normalize_chapter(cls, *, raw: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, str]:
        raw_chapter = raw.get("chapter")
        chapter_map = dict(raw_chapter) if isinstance(raw_chapter, dict) else {}

        title = str(chapter_map.get("title") or raw.get("title") or "").strip()
        content = str(chapter_map.get("content") or raw.get("content") or "").strip()
        summary = str(chapter_map.get("summary") or raw.get("summary") or "").strip()

        if not content and segments:
            content = "\n".join(
                str(item.get("content") or "").strip()
                for item in segments
                if str(item.get("content") or "").strip()
            ).strip()

        if not title:
            title = cls._fallback_title(content)

        if not summary and content:
            summary = cls._auto_summary(content)

        return {
            "title": title or "未命名章节",
            "content": content,
            "summary": summary,
        }

    @staticmethod
    def _normalize_mode(raw_mode: Any, *, fallback: str) -> str:
        mode = str(raw_mode or fallback or "draft").strip().lower()
        return mode if mode in {"draft", "revision"} else "draft"

    @staticmethod
    def _normalize_status(raw_status: Any) -> str:
        status = str(raw_status or "success").strip().lower()
        return status if status in {"success", "failed"} else "success"

    @staticmethod
    def _auto_summary(text: str, max_len: int = 140) -> str:
        content = str(text or "").strip()
        if not content:
            return ""
        compact = re.sub(r"\s+", " ", content)
        if len(compact) <= max_len:
            return compact
        return compact[: max_len - 1].rstrip() + "…"

    @staticmethod
    def _fallback_title(text: str, max_len: int = 24) -> str:
        content = re.sub(r"\s+", " ", str(text or "").strip())
        if not content:
            return ""
        if len(content) <= max_len:
            return content
        return content[: max_len - 1].rstrip() + "…"

    @staticmethod
    def _estimate_word_count(text: str) -> int:
        source = str(text or "").strip()
        if not source:
            return 0
        words = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", source)
        if words:
            return len(words)
        return len(source)
