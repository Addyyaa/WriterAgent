"""上下文压缩 LLM 步的输出 JSON Schema（与 HybridContextCompressor 对齐）。"""

from __future__ import annotations

from typing import Any

CONTEXT_COMPRESSION_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["compressed"],
    "properties": {
        "compressed": {"type": "string"},
    },
    "additionalProperties": True,
}
