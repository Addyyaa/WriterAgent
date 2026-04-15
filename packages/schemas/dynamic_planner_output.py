"""动态规划器 LLM 输出 JSON Schema（与 OpenAICompatibleDynamicPlanner 解析逻辑对齐）。"""

from __future__ import annotations

from typing import Any

_PLANNER_NODE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "step_key",
        "step_type",
        "workflow_type",
        "agent_name",
        "depends_on",
        "input_json",
    ],
    "properties": {
        "step_key": {"type": "string"},
        "step_type": {"type": "string"},
        "workflow_type": {"type": "string"},
        "agent_name": {"type": "string"},
        "role_id": {"type": "string"},
        "strategy_mode": {"type": ["string", "null"]},
        "depends_on": {"type": "array", "items": {"type": "string"}},
        "input_json": {"type": "object", "additionalProperties": True},
    },
    "additionalProperties": True,
}

DYNAMIC_PLANNER_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["workflow_type", "writing_goal", "context"],
    "properties": {
        "workflow_type": {"type": "string"},
        "writing_goal": {"type": "string"},
        "context": {"type": "object", "additionalProperties": True},
    },
    "additionalProperties": True,
}

DYNAMIC_PLANNER_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["nodes", "retry_policy", "fallback_policy"],
    "properties": {
        "nodes": {"type": "array", "items": _PLANNER_NODE_SCHEMA},
        "retry_policy": {"type": "object", "additionalProperties": True},
        "fallback_policy": {"type": "object", "additionalProperties": True},
    },
    "additionalProperties": True,
}
