"""动态规划器 LLM 输出 JSON Schema（与 OpenAICompatibleDynamicPlanner 解析逻辑对齐）。

知识字段（required_slots、preferred_tools 等）默认放在 ``properties`` 中，而不并入
``required``：历史 ``plan_json`` 与旧模型输出常缺这些键，若一律 required 会导致 strict
校验失败、整批规划不可用。需要强制契约时，请使用 ``dynamic_planner_output_schema(
strict_node_knowledge=True)`` 并配合环境 ``WRITER_PLANNER_STRICT_NODE_KNOWLEDGE``。
生产默认保持宽松（``strict_node_knowledge=False``），以降低历史 plan 与供应商 JSON 模式失败率。
"""

from __future__ import annotations

import copy
from typing import Any

# 严格模式下并入节点 required 的知识合同键（数组可为空，fallback_when_missing 可为 null）
_PLANNER_NODE_STRICT_EXTRA_REQUIRED: tuple[str, ...] = (
    "required_slots",
    "preferred_tools",
    "must_verify_facts",
    "allowed_assumptions",
    "fallback_when_missing",
)

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


def dynamic_planner_output_schema(*, strict_node_knowledge: bool = False) -> dict[str, Any]:
    """返回规划器输出 JSON Schema；strict 时每个 node 必须含知识合同字段。"""
    if not strict_node_knowledge:
        return DYNAMIC_PLANNER_OUTPUT_SCHEMA
    schema = copy.deepcopy(DYNAMIC_PLANNER_OUTPUT_SCHEMA)
    node = copy.deepcopy(_PLANNER_NODE_SCHEMA)
    merged = list(node["required"])
    for key in _PLANNER_NODE_STRICT_EXTRA_REQUIRED:
        if key not in merged:
            merged.append(key)
    node["required"] = merged
    schema["properties"] = dict(schema["properties"])
    schema["properties"]["nodes"] = {"type": "array", "items": node}
    return schema
