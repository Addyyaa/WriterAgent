"""从 planner_bootstrap 输出抽取知识感知字段，供检索循环与编排透传。"""

from __future__ import annotations

import re
from typing import Any

from packages.workflows.orchestration.agent_output_envelope import step_agent_view

_SLOT_NORMALIZE_RE = re.compile(r"[\s\-]+")


def _norm_slot(raw: str) -> str:
    s = str(raw or "").strip().lower()
    if not s:
        return ""
    return _SLOT_NORMALIZE_RE.sub("_", s)


def extract_planner_retrieval_slots(planner_step_output: dict[str, Any] | None) -> list[str]:
    """合并 global_required_slots 与各 step.required_slots，去重保序。"""
    if not planner_step_output:
        return []
    view = step_agent_view(planner_step_output)
    if not view:
        view = dict(planner_step_output)
    out: list[str] = []
    for item in list(view.get("global_required_slots") or []):
        slot = _norm_slot(str(item))
        if slot and slot not in out:
            out.append(slot)
    for step in list(view.get("steps") or []):
        if not isinstance(step, dict):
            continue
        for item in list(step.get("required_slots") or []):
            slot = _norm_slot(str(item))
            if slot and slot not in out:
                out.append(slot)
    return out


def extract_planner_verify_facts(planner_step_output: dict[str, Any] | None) -> list[str]:
    """收集各 step.must_verify_facts（去重）。"""
    if not planner_step_output:
        return []
    view = step_agent_view(planner_step_output)
    if not view:
        view = dict(planner_step_output)
    out: list[str] = []
    for step in list(view.get("steps") or []):
        if not isinstance(step, dict):
            continue
        for item in list(step.get("must_verify_facts") or []):
            t = str(item or "").strip()
            if t and t not in out:
                out.append(t)
    return out


def planner_knowledge_meta(planner_step_output: dict[str, Any] | None) -> dict[str, Any]:
    """写入步骤 output 侧车 meta，便于审计与前端展示。"""
    return {
        "planner_retrieval_slots": extract_planner_retrieval_slots(planner_step_output),
        "planner_must_verify_facts": extract_planner_verify_facts(planner_step_output),
    }
