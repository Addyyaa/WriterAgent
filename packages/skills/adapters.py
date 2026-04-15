from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Protocol

from packages.skills.registry import SkillSpec


class SkillToolAdapter(Protocol):
    name: str

    def prepare(
        self,
        *,
        spec: SkillSpec,
        phase: str,
        payload: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        ...

    def execute(
        self,
        *,
        spec: SkillSpec,
        phase: str,
        prepared: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        ...

    def verify(
        self,
        *,
        spec: SkillSpec,
        phase: str,
        prepared: dict[str, Any],
        executed: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        ...

    def summarize(
        self,
        *,
        spec: SkillSpec,
        phase: str,
        prepared: dict[str, Any],
        executed: dict[str, Any],
        verified: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class AdapterExecutionResult:
    findings: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    changed_spans: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    no_effect_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


class BaseSkillToolAdapter:
    name: str = "base"

    def prepare(
        self,
        *,
        spec: SkillSpec,
        phase: str,
        payload: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        del spec, phase, context
        return {"payload": dict(payload or {})}

    def execute(
        self,
        *,
        spec: SkillSpec,
        phase: str,
        prepared: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        del spec, phase, context
        return dict(prepared or {})

    def verify(
        self,
        *,
        spec: SkillSpec,
        phase: str,
        prepared: dict[str, Any],
        executed: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        del spec, phase, prepared, context
        return dict(executed or {})

    def summarize(
        self,
        *,
        spec: SkillSpec,
        phase: str,
        prepared: dict[str, Any],
        executed: dict[str, Any],
        verified: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        del spec, phase, prepared, executed, context
        return dict(verified or {})


def _constraints_root(payload: dict[str, Any]) -> dict[str, Any] | None:
    """兼容大包 story_constraints 与 Assembler 的 state.story_assets。"""
    raw = payload.get("story_constraints")
    if isinstance(raw, dict):
        return raw
    raw = payload.get("constraints")
    if isinstance(raw, dict):
        return raw
    state = payload.get("state")
    if isinstance(state, dict):
        sa = state.get("story_assets")
        if isinstance(sa, dict):
            return sa
    return None


class ConstraintAdapter(BaseSkillToolAdapter):
    name = "constraint"

    def summarize(
        self,
        *,
        spec: SkillSpec,
        phase: str,
        prepared: dict[str, Any],
        executed: dict[str, Any],
        verified: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        del spec, phase, prepared, executed, context
        payload = dict((verified or {}).get("payload") or {})
        constraints = _constraints_root(payload)
        if not isinstance(constraints, dict):
            return {"no_effect_reason": "未发现可解析的约束对象（story_constraints/constraints）"}

        required_keys = ("characters", "world_entries", "timeline_events")
        missing = [key for key in required_keys if not list(constraints.get(key) or [])]
        findings = [
            {
                "type": "constraint_missing",
                "severity": "warning",
                "message": f"约束字段为空: {key}",
                "evidence": {"key": key},
            }
            for key in missing
        ]
        evidence = [
            {
                "type": "constraint_keys",
                "payload": {
                    "keys": sorted(str(k) for k in constraints.keys()),
                    "missing_required": missing,
                },
            }
        ]
        return {
            "findings": findings,
            "evidence": evidence,
            "metrics": {
                "constraint_keys": int(len(constraints.keys())),
                "constraint_missing_required": int(len(missing)),
            },
            "no_effect_reason": None if findings else "约束完整，无需额外干预",
        }


class TimelineAdapter(BaseSkillToolAdapter):
    name = "timeline"

    def summarize(
        self,
        *,
        spec: SkillSpec,
        phase: str,
        prepared: dict[str, Any],
        executed: dict[str, Any],
        verified: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        del spec, phase, prepared, executed, context
        payload = dict((verified or {}).get("payload") or {})
        events = _extract_list(
            payload,
            ("story_constraints", "timeline_events"),
            ("state", "story_assets", "timeline_events"),
            ("timeline_events",),
            ("events",),
        )
        if not events:
            return {"no_effect_reason": "未发现 timeline events"}

        seen: set[str] = set()
        duplicate_keys: list[str] = []
        for item in events:
            if not isinstance(item, dict):
                continue
            marker = "|".join(
                [
                    str(item.get("id") or "").strip(),
                    str(item.get("name") or item.get("title") or "").strip(),
                    str(item.get("time") or item.get("start") or "").strip(),
                ]
            )
            if not marker.strip("|"):
                continue
            if marker in seen:
                duplicate_keys.append(marker)
            seen.add(marker)

        findings = [
            {
                "type": "timeline_duplicate",
                "severity": "warning",
                "message": "检测到重复时间线事件",
                "evidence": {"key": marker},
            }
            for marker in duplicate_keys
        ]
        evidence = [{"type": "timeline_count", "payload": {"events": len(events)}}]
        return {
            "findings": findings,
            "evidence": evidence,
            "metrics": {
                "timeline_events_count": int(len(events)),
                "timeline_duplicate_count": int(len(duplicate_keys)),
            },
            "no_effect_reason": None if findings else "时间线事件未发现结构冲突",
        }


class CanonAdapter(BaseSkillToolAdapter):
    name = "canon"

    def summarize(
        self,
        *,
        spec: SkillSpec,
        phase: str,
        prepared: dict[str, Any],
        executed: dict[str, Any],
        verified: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        del spec, phase, prepared, executed, context
        payload = dict((verified or {}).get("payload") or {})
        canon_names: list[str] = []

        for item in _extract_list(
            payload,
            ("story_constraints", "characters"),
            ("state", "story_assets", "characters"),
            ("characters",),
        ):
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("character_name") or "").strip()
                if name:
                    canon_names.append(name)
        for item in _extract_list(
            payload,
            ("story_constraints", "world_entries"),
            ("state", "story_assets", "world_entries"),
            ("world_entries",),
        ):
            if isinstance(item, dict):
                name = str(item.get("term") or item.get("name") or "").strip()
                if name:
                    canon_names.append(name)

        text_blob = " ".join(
            [
                str(payload.get("content") or ""),
                str(payload.get("summary") or ""),
                str(payload.get("notes") or ""),
            ]
        ).strip()
        if not canon_names:
            return {"no_effect_reason": "未发现可用于校验的 canon 实体"}
        hits = [name for name in canon_names if text_blob and name in text_blob]
        findings: list[dict[str, Any]] = []
        if text_blob and not hits:
            findings.append(
                {
                    "type": "canon_unreferenced",
                    "severity": "warning",
                    "message": "文本中未命中已知 canon 实体",
                    "evidence": {"canon_entities": canon_names[:8]},
                }
            )
        return {
            "findings": findings,
            "evidence": [
                {
                    "type": "canon_hits",
                    "payload": {
                        "canon_entities": int(len(canon_names)),
                        "hit_count": int(len(hits)),
                    },
                }
            ],
            "metrics": {
                "canon_entity_count": int(len(canon_names)),
                "canon_hit_count": int(len(hits)),
            },
            "no_effect_reason": None if findings else "canon 校验通过",
        }


class LogicConflictAdapter(BaseSkillToolAdapter):
    name = "logic_conflict"

    def summarize(
        self,
        *,
        spec: SkillSpec,
        phase: str,
        prepared: dict[str, Any],
        executed: dict[str, Any],
        verified: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        del spec, phase, prepared, executed, context
        payload = dict((verified or {}).get("payload") or {})
        constraints = dict(_constraints_root(payload) or {})
        overlaps: list[str] = []
        must_do = {str(item).strip() for item in list(constraints.get("must_do") or []) if str(item).strip()}
        must_not = {str(item).strip() for item in list(constraints.get("must_not") or []) if str(item).strip()}
        overlaps.extend(sorted(must_do & must_not))

        findings = [
            {
                "type": "logic_conflict",
                "severity": "error",
                "message": "检测到互斥约束同时存在",
                "evidence": {"item": item},
            }
            for item in overlaps
        ]
        return {
            "findings": findings,
            "evidence": [{"type": "logic_overlap", "payload": {"items": overlaps}}],
            "metrics": {"logic_overlap_count": int(len(overlaps))},
            "no_effect_reason": None if findings else "未检测到显式逻辑冲突",
        }


class PlanGraphAdapter(BaseSkillToolAdapter):
    name = "plan_graph"

    def summarize(
        self,
        *,
        spec: SkillSpec,
        phase: str,
        prepared: dict[str, Any],
        executed: dict[str, Any],
        verified: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        del spec, phase, prepared, executed, context
        payload = dict((verified or {}).get("payload") or {})
        tasks = _extract_list(payload, ("task_graph", "nodes"), ("tasks",), ("nodes",))
        if not tasks:
            return {"no_effect_reason": "未发现 task graph 节点"}

        node_ids = set()
        edges: dict[str, list[str]] = {}
        for item in tasks:
            if not isinstance(item, dict):
                continue
            node_id = str(item.get("id") or item.get("step_key") or "").strip()
            if not node_id:
                continue
            node_ids.add(node_id)
            deps = [str(dep).strip() for dep in list(item.get("depends_on") or []) if str(dep).strip()]
            edges[node_id] = deps

        missing_deps: list[tuple[str, str]] = []
        for node_id, deps in edges.items():
            for dep in deps:
                if dep not in node_ids:
                    missing_deps.append((node_id, dep))

        has_cycle = _detect_cycle(edges)
        findings: list[dict[str, Any]] = [
            {
                "type": "task_graph_missing_dependency",
                "severity": "error",
                "message": "任务依赖引用了不存在的节点",
                "evidence": {"node": node, "missing_dep": dep},
            }
            for node, dep in missing_deps
        ]
        if has_cycle:
            findings.append(
                {
                    "type": "task_graph_cycle",
                    "severity": "error",
                    "message": "任务图存在循环依赖",
                    "evidence": {"cycle_detected": True},
                }
            )
        return {
            "findings": findings,
            "evidence": [
                {"type": "task_graph_summary", "payload": {"nodes": len(node_ids), "edges": sum(len(v) for v in edges.values())}}
            ],
            "metrics": {
                "task_graph_nodes": int(len(node_ids)),
                "task_graph_edges": int(sum(len(v) for v in edges.values())),
                "task_graph_missing_dependencies": int(len(missing_deps)),
                "task_graph_has_cycle": 1 if has_cycle else 0,
            },
            "no_effect_reason": None if findings else "task graph 校验通过",
        }


class QASpecAdapter(BaseSkillToolAdapter):
    name = "qa_spec"

    def summarize(
        self,
        *,
        spec: SkillSpec,
        phase: str,
        prepared: dict[str, Any],
        executed: dict[str, Any],
        verified: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        del spec, prepared, executed, context
        payload = dict((verified or {}).get("payload") or {})
        qa = payload.get("qa_spec")
        if not isinstance(qa, dict):
            qa = payload.get("skill_quality_gate")
        if not isinstance(qa, dict):
            # after_generate 校验的是模型输出，多数 agent 不会回传 qa_spec；约束已在 before 阶段注入 skill_quality_gate
            if str(phase or "").strip().lower() == "after_generate":
                return {
                    "findings": [],
                    "evidence": [],
                    "metrics": {"qa_spec_after_generate": 1, "qa_spec_in_output": 0},
                    "no_effect_reason": None,
                }
            return {"no_effect_reason": "未发现 qa_spec/skill_quality_gate"}

        required = (
            "must_have_risk_item",
            "must_have_fallback_strategy",
            "must_have_acceptance_criteria",
        )
        missing = [key for key in required if key not in qa]
        findings = [
            {
                "type": "qa_spec_missing_item",
                "severity": "warning",
                "message": f"QA 规范缺少关键项: {key}",
                "evidence": {"key": key},
            }
            for key in missing
        ]
        return {
            "findings": findings,
            "evidence": [{"type": "qa_spec_keys", "payload": {"keys": sorted(str(k) for k in qa.keys())}}],
            "metrics": {
                "qa_spec_key_count": int(len(qa.keys())),
                "qa_spec_missing_required": int(len(missing)),
            },
            "no_effect_reason": None,
        }


class ContextSynthesisAdapter(BaseSkillToolAdapter):
    name = "context_synthesis"

    def summarize(
        self,
        *,
        spec: SkillSpec,
        phase: str,
        prepared: dict[str, Any],
        executed: dict[str, Any],
        verified: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        del spec, phase, prepared, executed, context
        payload = dict((verified or {}).get("payload") or {})
        contexts = _extract_list(
            payload,
            ("retrieved_contexts",),
            ("memory_context",),
            ("state", "chapter_memory", "items"),
            ("contexts",),
        )
        if not contexts:
            return {
                "findings": [
                    {
                        "type": "context_missing",
                        "severity": "warning",
                        "message": "上下文集合为空，可能影响下游生成质量",
                    }
                ],
                "evidence": [],
                "metrics": {"context_items": 0},
            }
        sources = {
            str(item.get("source") or item.get("source_type") or "").strip()
            for item in contexts
            if isinstance(item, dict)
        }
        sources.discard("")
        estimated_chars = sum(
            len(str(item.get("text") or item.get("content") or ""))
            for item in contexts
            if isinstance(item, dict)
        )
        return {
            "evidence": [
                {
                    "type": "context_provenance",
                    "payload": {
                        "items": int(len(contexts)),
                        "unique_sources": int(len(sources)),
                    },
                }
            ],
            "metrics": {
                "context_items": int(len(contexts)),
                "context_unique_sources": int(len(sources)),
                "context_estimated_tokens": int(max(1, estimated_chars // 4)),
            },
            "no_effect_reason": "context 已综合，无硬冲突",
        }


class InternalFactProvider(BaseSkillToolAdapter):
    name = "internal_fact_provider"

    def summarize(
        self,
        *,
        spec: SkillSpec,
        phase: str,
        prepared: dict[str, Any],
        executed: dict[str, Any],
        verified: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        del spec, phase, prepared, executed, context
        payload = dict((verified or {}).get("payload") or {})
        claims = _extract_claims(payload)
        known_facts = _extract_texts(payload.get("facts")) + _extract_texts(payload.get("canon_memory"))
        if not claims:
            return {"no_effect_reason": "未提供 claims，跳过内部事实核验"}
        supported = 0
        unsupported_claims: list[str] = []
        for claim in claims:
            if any(_contains_overlap(claim, fact) for fact in known_facts):
                supported += 1
            else:
                unsupported_claims.append(claim)
        findings = [
            {
                "type": "fact_internal_unsupported",
                "severity": "warning",
                "message": "未在内部知识中找到充分支持",
                "evidence": {"claim": claim},
            }
            for claim in unsupported_claims
        ]
        return {
            "findings": findings,
            "evidence": [
                {
                    "type": "fact_checking_internal",
                    "source_scope": "internal",
                    "payload": {
                        "claims": int(len(claims)),
                        "supported": int(supported),
                    },
                }
            ],
            "metrics": {
                "fact_internal_claim_count": int(len(claims)),
                "fact_internal_supported_count": int(supported),
            },
            "no_effect_reason": None if findings else "内部事实核验通过",
        }


class ExternalFactProvider(BaseSkillToolAdapter):
    name = "external_fact_provider"

    def summarize(
        self,
        *,
        spec: SkillSpec,
        phase: str,
        prepared: dict[str, Any],
        executed: dict[str, Any],
        verified: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        del spec, phase, prepared, executed, context
        payload = dict((verified or {}).get("payload") or {})
        claims = _extract_claims(payload)
        external_sources = _extract_texts(payload.get("external_sources")) + _extract_texts(payload.get("source_urls"))
        if not claims:
            return {"no_effect_reason": "未提供 claims，跳过外部事实核验"}
        if not external_sources:
            return {
                "findings": [
                    {
                        "type": "fact_external_unverifiable",
                        "severity": "warning",
                        "message": "外部事实源不可用，结论标记为 unverifiable",
                        "evidence": {"unverifiable_reason": "missing_external_sources"},
                    }
                ],
                "evidence": [
                    {
                        "type": "fact_checking_external",
                        "source_scope": "external",
                        "payload": {"claims": int(len(claims)), "available_sources": 0},
                    }
                ],
                "metrics": {
                    "fact_external_claim_count": int(len(claims)),
                    "fact_external_available_sources": 0,
                    "fact_external_unverifiable_count": int(len(claims)),
                },
            }

        return {
            "evidence": [
                {
                    "type": "fact_checking_external",
                    "source_scope": "external",
                    "payload": {
                        "claims": int(len(claims)),
                        "available_sources": int(len(external_sources)),
                    },
                }
            ],
            "metrics": {
                "fact_external_claim_count": int(len(claims)),
                "fact_external_available_sources": int(len(external_sources)),
                "fact_external_unverifiable_count": 0,
            },
            "no_effect_reason": "外部事实源可用，待下游模型归纳",
        }


class SkillToolAdapterRegistry:
    def __init__(self, adapters: dict[str, SkillToolAdapter] | None = None) -> None:
        builtins: dict[str, SkillToolAdapter] = {
            "constraint": ConstraintAdapter(),
            "timeline": TimelineAdapter(),
            "canon": CanonAdapter(),
            "logic_conflict": LogicConflictAdapter(),
            "plan_graph": PlanGraphAdapter(),
            "qa_spec": QASpecAdapter(),
            "context_synthesis": ContextSynthesisAdapter(),
            "internal_fact_provider": InternalFactProvider(),
            "external_fact_provider": ExternalFactProvider(),
        }
        if adapters:
            builtins.update(adapters)
        self._adapters = builtins

    def get(self, adapter_name: str) -> SkillToolAdapter | None:
        key = str(adapter_name or "").strip().lower()
        if not key:
            return None
        return self._adapters.get(key)

    def run(
        self,
        *,
        adapter_name: str,
        spec: SkillSpec,
        phase: str,
        payload: dict[str, Any],
        context: Any,
    ) -> AdapterExecutionResult:
        adapter = self.get(adapter_name)
        if adapter is None:
            return AdapterExecutionResult(
                warnings=[f"adapter 不存在: {adapter_name}"],
                no_effect_reason=f"adapter_not_found:{adapter_name}",
            )
        begin = perf_counter()
        prepared = adapter.prepare(spec=spec, phase=phase, payload=payload, context=context)
        executed = adapter.execute(spec=spec, phase=phase, prepared=prepared, context=context)
        verified = adapter.verify(
            spec=spec,
            phase=phase,
            prepared=prepared,
            executed=executed,
            context=context,
        )
        summary = adapter.summarize(
            spec=spec,
            phase=phase,
            prepared=prepared,
            executed=executed,
            verified=verified,
            context=context,
        )
        elapsed_ms = int((perf_counter() - begin) * 1000)
        metrics = dict(summary.get("metrics") or {})
        metrics.setdefault("latency_ms", elapsed_ms)
        return AdapterExecutionResult(
            findings=_normalize_list_of_dicts(summary.get("findings")),
            evidence=_normalize_list_of_dicts(summary.get("evidence")),
            changed_spans=_normalize_list_of_dicts(summary.get("changed_spans")),
            metrics=metrics,
            no_effect_reason=_normalize_str(summary.get("no_effect_reason")),
            warnings=[str(item) for item in list(summary.get("warnings") or []) if str(item).strip()],
        )


def _normalize_list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            out.append(dict(item))
        elif isinstance(item, str) and item.strip():
            out.append({"message": item.strip()})
    return out


def _normalize_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _extract_list(payload: dict[str, Any], *paths: tuple[str, ...]) -> list[Any]:
    for path in paths:
        value = _extract_path(payload, path)
        if isinstance(value, list):
            return list(value)
    return []


def _extract_path(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _extract_texts(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    out.append(text)
            elif isinstance(item, dict):
                for key in ("text", "content", "fact", "value", "url", "source"):
                    txt = str(item.get(key) or "").strip()
                    if txt:
                        out.append(txt)
                        break
        return out
    if isinstance(value, dict):
        out = []
        for key in ("text", "content", "fact", "value", "url", "source"):
            txt = str(value.get(key) or "").strip()
            if txt:
                out.append(txt)
        return out
    return []


def _extract_claims(payload: dict[str, Any]) -> list[str]:
    claims = _extract_texts(payload.get("claims"))
    if claims:
        return claims
    issues = payload.get("issues")
    if isinstance(issues, list):
        out: list[str] = []
        for item in issues:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    out.append(text)
            elif isinstance(item, dict):
                text = str(item.get("claim") or item.get("issue") or item.get("description") or "").strip()
                if text:
                    out.append(text)
        if out:
            return out
    text_claim = str(payload.get("claim") or "").strip()
    return [text_claim] if text_claim else []


def _contains_overlap(left: str, right: str) -> bool:
    lhs = [token for token in left.lower().split() if token]
    rhs = right.lower()
    if not lhs or not rhs:
        return False
    hit = sum(1 for token in lhs if token in rhs)
    return hit >= max(1, len(lhs) // 3)


def _detect_cycle(edges: dict[str, list[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str) -> bool:
        if node in visited:
            return False
        if node in visiting:
            return True
        visiting.add(node)
        for nxt in edges.get(node, []):
            if nxt in edges and dfs(nxt):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(dfs(node) for node in edges.keys())
