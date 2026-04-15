"""Agent 步骤 LLM 输出的 view/meta/raw 信封辅助。"""

from __future__ import annotations

from typing import Any

from packages.llm.text_generation.base import TextGenerationResult


def build_agent_step_meta_raw(
    *,
    result: TextGenerationResult,
    schema_ref: str,
    schema_version: str,
    prompt_hash: str,
    strategy_version: str,
    skills_executed_count: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """从生成结果抽取可审计 meta 与精简 raw（避免整份 provider 响应落库）。"""
    raw_body = dict(result.raw_response_json or {})
    usage: dict[str, Any] = {}
    u = raw_body.get("usage")
    if isinstance(u, dict):
        usage = {
            k: u.get(k)
            for k in ("prompt_tokens", "completion_tokens", "total_tokens")
            if u.get(k) is not None
        }

    finish_reason: Any = None
    choices = raw_body.get("choices")
    if isinstance(choices, list) and choices:
        ch0 = choices[0]
        if isinstance(ch0, dict):
            finish_reason = ch0.get("finish_reason")

    meta: dict[str, Any] = {
        "schema_ref": schema_ref,
        "schema_version": schema_version,
        "prompt_hash": prompt_hash,
        "strategy_version": strategy_version,
        "mock_mode": bool(result.is_mock),
        "provider": result.provider,
        "model": result.model,
        "skills_executed_count": int(skills_executed_count),
    }
    if usage:
        meta["usage"] = usage
    if finish_reason is not None:
        meta["finish_reason"] = finish_reason

    response_summary: dict[str, Any] = {}
    if raw_body.get("id") is not None:
        response_summary["id"] = raw_body.get("id")
    if raw_body.get("model") is not None:
        response_summary["model"] = raw_body.get("model")
    if finish_reason is not None:
        response_summary["finish_reason"] = finish_reason
    if usage:
        response_summary["usage"] = usage

    raw_out: dict[str, Any] = {
        "text": str(result.text or ""),
    }
    if response_summary:
        raw_out["response_summary"] = response_summary

    return meta, raw_out


def step_agent_view(step_output: dict[str, Any] | None) -> dict[str, Any]:
    """从 workflow步骤的 output_json 取结构化视图：优先 view，兼容历史 agent_output。"""
    step = dict(step_output or {})
    view = step.get("view")
    if isinstance(view, dict):
        return dict(view)
    legacy = step.get("agent_output")
    if isinstance(legacy, dict):
        return dict(legacy)
    return {}


def wrap_view_schema_for_consumption(inner: dict[str, Any]) -> dict[str, Any]:
    """将角色 output_schema（仅描述 view 形状）包装为含 view 根的契约 schema。"""
    return {
        "type": "object",
        "required": ["view"],
        "properties": {"view": dict(inner)},
        "additionalProperties": True,
    }
