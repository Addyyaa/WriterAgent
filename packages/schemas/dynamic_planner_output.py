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
        "required_slots": {
            "type": "array",
            "items": {"type": "string"},
            "description": "本节点执行前检索应覆盖的槽位（snake_case），供 planner_knowledge 与 RetrievalLoop 消费",
        },
        "preferred_tools": {
            "type": "array",
            "items": {"type": "string"},
            "description": "优先结构化工具/检索通道（如 character_inventory、memory_search）",
        },
        "must_verify_facts": {
            "type": "array",
            "items": {"type": "string"},
            "description": "动笔前须用证据核验的陈述（中文短句）",
        },
        "allowed_assumptions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "证据不足时允许的显式假设及边界",
        },
        "fallback_when_missing": {
            "type": ["string", "null"],
            "description": "关键信息缺失时的写作原则（一句）",
        },
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
