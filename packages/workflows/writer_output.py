from __future__ import annotations

import re
from typing import Any

from packages.core.utils.chapter_metrics import count_fiction_word_units


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

# ---------------------------------------------------------------------------
# User JSON：output_format.schema_ref / output_format.contract（全仓唯一真源）
# 契约 ID 统一为 writer.output.<variant>，与 prompt、校验、日志引用一致。
# ---------------------------------------------------------------------------
WRITER_OUTPUT_SCHEMA_REF_V2 = "apps/agents/writer_agent/output_schema.json"
WRITER_OUTPUT_SCHEMA_REF_DRAFT = "apps/agents/writer_agent/output_schema_draft.json"
WRITER_OUTPUT_SCHEMA_REF_LEGACY_INLINE = "inline://chapter_generation/legacy_output"

WRITER_OUTPUT_CONTRACT_V2 = "writer.output.v2"
WRITER_OUTPUT_CONTRACT_DRAFT = "writer.output.draft"
WRITER_OUTPUT_CONTRACT_LEGACY_FLAT = "writer.output.legacy_flat"


class WriterOutputAdapter:
    """将 writer 输出归一化为可消费的 writer.output.v2 形态（见 WRITER_OUTPUT_CONTRACT_V2）。"""

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

        title = cls._sanitize_text_field(title)
        content = cls._sanitize_text_field(content)
        summary = cls._sanitize_text_field(summary)

        segment_joined = "\n".join(
            str(item.get("content") or "").strip()
            for item in segments
            if str(item.get("content") or "").strip()
        ).strip()
        # 模型常把长叙事写在 segments，chapter.content 留成短摘要；落库与字数校验应以信息量更大的一侧为准（非压缩，是字段选择）。
        if segment_joined and count_fiction_word_units(segment_joined) > count_fiction_word_units(content):
            content = segment_joined

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
    def _sanitize_text_field(text: str) -> str:
        """清洗可能被 JSON/prompt 污染的文本字段。

        当 LLM 或 mock provider 将结构化 JSON 串误塞入文本字段时，
        尝试从中提取真正的自然语言内容。
        """
        import json as _json

        if not text:
            return text
        stripped = text.strip()
        if not stripped.startswith("{"):
            return text

        try:
            parsed = _json.loads(stripped)
        except Exception:
            return text

        if not isinstance(parsed, dict):
            return text

        for path in [
            ("chapter", "content"),
            ("content",),
            ("chapter", "title"),
            ("title",),
            ("chapter", "summary"),
            ("summary",),
        ]:
            node: Any = parsed
            for key in path:
                if isinstance(node, dict):
                    node = node.get(key)
                else:
                    node = None
                    break
            if isinstance(node, str) and len(node.strip()) > 10 and not node.strip().startswith("{"):
                return node.strip()

        return text

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
