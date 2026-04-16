"""context_bundle 决策型字段：summary 与根对象双写、读取时根优先。"""

from __future__ import annotations

from typing import Any

# 与 retrieval_agent / ContextPackage / RetrievalLoop 摘要层对齐的五段决策字段
DECISION_CONTEXT_KEYS: tuple[str, ...] = (
    "confirmed_facts",
    "current_states",
    "supporting_evidence",
    "conflicts",
    "information_gaps",
)

KEY_FACTS_KEY = "key_facts"


def _coerce_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def mirror_decision_fields_to_bundle_root(bundle: dict[str, Any]) -> None:
    """从 ``bundle['summary']`` 将五段决策字段拷贝到根对象（浅拷贝 list，避免与 summary 共享引用）。"""
    summary = bundle.get("summary")
    if not isinstance(summary, dict):
        return
    for key in DECISION_CONTEXT_KEYS:
        bundle[key] = _coerce_list(summary.get(key))


def mirror_key_facts_to_bundle_root(bundle: dict[str, Any]) -> None:
    """从 summary 拷贝 ``key_facts`` 到根对象（与五段对称，供 Writer/评测只读根级）。"""
    summary = bundle.get("summary")
    if not isinstance(summary, dict):
        return
    bundle[KEY_FACTS_KEY] = _coerce_list(summary.get(KEY_FACTS_KEY))


def mirror_context_bundle_lists_from_summary(bundle: dict[str, Any]) -> None:
    """对生产路径统一入口：五段 + key_facts 一次双写。"""
    mirror_decision_fields_to_bundle_root(bundle)
    mirror_key_facts_to_bundle_root(bundle)


def read_decision_fields_from_bundle(bundle: dict[str, Any]) -> dict[str, list[Any]]:
    """根键优先；缺失或 ``None`` 时回退 ``summary``。老数据仅含 summary 时行为与旧读取一致。"""
    summary = dict(bundle.get("summary") or {})
    out: dict[str, list[Any]] = {}
    for key in DECISION_CONTEXT_KEYS:
        if key in bundle and bundle[key] is not None:
            raw = bundle[key]
        else:
            raw = summary.get(key)
        out[key] = _coerce_list(raw)
    return out


def read_key_facts_from_bundle(bundle: dict[str, Any]) -> list[Any]:
    """key_facts：根优先，否则 summary。"""
    summary = dict(bundle.get("summary") or {})
    if KEY_FACTS_KEY in bundle and bundle[KEY_FACTS_KEY] is not None:
        return _coerce_list(bundle[KEY_FACTS_KEY])
    return _coerce_list(summary.get(KEY_FACTS_KEY))
