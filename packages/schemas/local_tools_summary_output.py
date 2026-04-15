"""本地项目列表工具链第二段 LLM 总结输入/输出 Schema（脚本与测试复用）。"""

from __future__ import annotations

from typing import Any

LOCAL_PROJECTS_SUMMARY_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["tool_result", "instruction"],
    "properties": {
        "tool_result": {"type": "object", "additionalProperties": True},
        "instruction": {"type": "string", "minLength": 1},
    },
    "additionalProperties": True,
}

LOCAL_PROJECTS_SUMMARY_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["overview", "project_titles", "notes"],
    "properties": {
        "overview": {"type": "string"},
        "project_titles": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "additionalProperties": True,
}
