"""AI 故事资产生成（Bootstrap）输出 JSON Schema，与 apps/agents/asset_generator/prompts 对齐。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_CHARACTER_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "name",
        "role_type",
        "narrative_function",
        "faction",
        "age",
        "wound",
        "want",
        "need",
        "personality",
        "motivation",
    ],
    "properties": {
        "name": {"type": "string"},
        "role_type": {"type": "string"},
        "narrative_function": {"type": "string"},
        "faction": {"type": "string"},
        "age": {"type": "number"},
        "wound": {"type": "string"},
        "want": {"type": "string"},
        "need": {"type": "string"},
        "personality": {"type": "string"},
        "motivation": {"type": "string"},
    },
    "additionalProperties": True,
}

_TENSION_PAIR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["characters", "surface_relation", "hidden_tension"],
    "properties": {
        "characters": {"type": "array", "items": {"type": "string"}},
        "surface_relation": {"type": "string"},
        "hidden_tension": {"type": "string"},
    },
    "additionalProperties": True,
}

_WORLD_ENTRY_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["title", "entry_type", "content", "narrative_purpose"],
    "properties": {
        "title": {"type": "string"},
        "entry_type": {"type": "string"},
        "content": {"type": "string"},
        "narrative_purpose": {"type": "string"},
    },
    "additionalProperties": True,
}

_CROSS_REFERENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["from", "to", "relation"],
    "properties": {
        "from": {"type": "string"},
        "to": {"type": "string"},
        "relation": {"type": "string"},
    },
    "additionalProperties": True,
}

_TIMELINE_EVENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "chapter_no",
        "title",
        "event_type",
        "description",
        "location",
        "characters_involved",
        "state_change",
    ],
    "properties": {
        "chapter_no": {"type": "number"},
        "title": {"type": "string"},
        "event_type": {"type": "string"},
        "description": {"type": "string"},
        "location": {"type": "string"},
        "characters_involved": {"type": "string"},
        "state_change": {"type": "string"},
    },
    "additionalProperties": True,
}

_FORESHADOWING_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "planted_chapter",
        "type",
        "planted_content",
        "surface_meaning",
        "true_meaning",
        "expected_payoff",
        "payoff_chapter",
        "emotional_target",
    ],
    "properties": {
        "planted_chapter": {"type": "number"},
        "type": {"type": "string"},
        "planted_content": {"type": "string"},
        "surface_meaning": {"type": "string"},
        "true_meaning": {"type": "string"},
        "expected_payoff": {"type": "string"},
        "payoff_chapter": {"type": "number"},
        "emotional_target": {"type": "string"},
    },
    "additionalProperties": True,
}

OUTLINE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["title", "content", "promise", "central_question"],
    "properties": {
        "title": {"type": "string"},
        "content": {"type": "string"},
        "promise": {"type": "string"},
        "central_question": {"type": "string"},
    },
    "additionalProperties": True,
}

CHARACTERS_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["characters", "tension_pairs"],
    "properties": {
        "characters": {"type": "array", "items": _CHARACTER_ITEM_SCHEMA},
        "tension_pairs": {"type": "array", "items": _TENSION_PAIR_SCHEMA},
    },
    "additionalProperties": True,
}

WORLD_ENTRIES_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["entries", "cross_references"],
    "properties": {
        "entries": {"type": "array", "items": _WORLD_ENTRY_ITEM_SCHEMA},
        "cross_references": {"type": "array", "items": _CROSS_REFERENCE_SCHEMA},
    },
    "additionalProperties": True,
}

TIMELINE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["events", "causal_chain"],
    "properties": {
        "events": {"type": "array", "items": _TIMELINE_EVENT_SCHEMA},
        "causal_chain": {"type": "string"},
    },
    "additionalProperties": True,
}

FORESHADOWING_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["items", "strategy_note"],
    "properties": {
        "items": {"type": "array", "items": _FORESHADOWING_ITEM_SCHEMA},
        "strategy_note": {"type": "string"},
    },
    "additionalProperties": True,
}

ASSET_GENERATOR_OUTPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "outline": OUTLINE_OUTPUT_SCHEMA,
    "characters": CHARACTERS_OUTPUT_SCHEMA,
    "world_entries": WORLD_ENTRIES_OUTPUT_SCHEMA,
    "timeline": TIMELINE_OUTPUT_SCHEMA,
    "foreshadowing": FORESHADOWING_OUTPUT_SCHEMA,
}


@dataclass(frozen=True)
class AssetGeneratorSchemaBundle:
    """资产生成单次 LLM 调用的 schema 与 function calling 元数据。"""

    response_schema: dict[str, Any]
    response_schema_name: str
    function_name: str
    function_description: str


def asset_generator_schema_bundle(asset_type: str) -> AssetGeneratorSchemaBundle:
    """返回指定资产类型的输出约束；asset_type 须为已注册的生成类型。"""
    schema = ASSET_GENERATOR_OUTPUT_SCHEMAS.get(asset_type)
    if not isinstance(schema, dict) or not schema:
        raise KeyError(f"未知资产类型或无 schema: {asset_type!r}")
    safe = asset_type.replace("-", "_")
    name = f"ai_asset_{safe}_output"
    desc_map = {
        "outline": "Return narrative arc blueprint: title, content, promise, central_question.",
        "characters": "Return character constellation: characters and tension_pairs.",
        "world_entries": "Return world logic: entries and cross_references.",
        "timeline": "Return narrative rhythm: events and causal_chain.",
        "foreshadowing": "Return foreshadowing architecture: items and strategy_note.",
    }
    return AssetGeneratorSchemaBundle(
        response_schema=schema,
        response_schema_name=name,
        function_name=name,
        function_description=str(desc_map.get(asset_type, "Return structured story asset JSON.")),
    )
