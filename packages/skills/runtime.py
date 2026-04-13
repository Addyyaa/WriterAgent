from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Literal, Protocol

from packages.skills.adapters import SkillToolAdapterRegistry
from packages.skills.registry import SkillSpec

SkillMode = Literal["prompt_only", "local_code", "hybrid"]
ExecutionMode = Literal["legacy", "shadow", "active"]
FallbackPolicy = Literal["pass_through", "warn_only", "hard_fail"]


class SkillRuntimeError(RuntimeError):
    """技能运行时错误。"""


@dataclass(frozen=True)
class SkillRequest:
    trace_id: str | None
    skill_name: str
    input: dict[str, Any]
    context: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillResult:
    success: bool
    mode_used: SkillMode
    output: dict[str, Any] | None = None
    findings: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    changed_spans: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    fallback_used: bool = False
    fallback_reason: str | None = None
    no_effect_reason: str | None = None


@dataclass(frozen=True)
class SkillRuntimeContext:
    trace_id: str | None
    role_id: str
    workflow_type: str
    step_key: str
    mode: str | None = None


@dataclass(frozen=True)
class SkillRuntimeRun:
    skill_id: str
    skill_version: str
    phase: str
    status: str
    skill_mode: str = "prompt_only"
    execution_mode: str = "legacy"
    mode_used: str = "prompt_only"
    fallback_policy: str = "warn_only"
    fallback_used: bool = False
    fallback_reason: str | None = None
    applied: bool = False
    effective_delta: int = 0
    warnings: list[str] = field(default_factory=list)
    changed_spans: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    no_effect_reason: str | None = None


@dataclass(frozen=True)
class SkillBeforeResult:
    system_prompt: str
    input_payload: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    runs: list[SkillRuntimeRun] = field(default_factory=list)
    effective_delta: int = 0


@dataclass(frozen=True)
class SkillAfterResult:
    output_payload: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    runs: list[SkillRuntimeRun] = field(default_factory=list)
    effective_delta: int = 0


class SkillExecutor(Protocol):
    def before_generate(
        self,
        *,
        spec: SkillSpec,
        system_prompt: str,
        input_payload: dict[str, Any],
        context: SkillRuntimeContext,
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        ...

    def after_generate(
        self,
        *,
        spec: SkillSpec,
        output_payload: dict[str, Any],
        context: SkillRuntimeContext,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        ...


class PolicySkillExecutor:
    """轻量策略执行器：支持 prompt/context 变换与输出补强。"""

    def before_generate(
        self,
        *,
        spec: SkillSpec,
        system_prompt: str,
        input_payload: dict[str, Any],
        context: SkillRuntimeContext,
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        sid = str(spec.id or "").strip().lower()
        prompt = str(system_prompt or "")
        payload = copy.deepcopy(dict(input_payload or {}))
        applied = False
        warnings: list[str] = []
        changed_spans: list[dict[str, Any]] = []

        instruction = self._instruction_for_skill(skill_id=sid, context=context)
        if instruction:
            marker = f"[Skill:{sid}]"
            line = f"{marker} {instruction}"
            if line not in prompt:
                prompt = (prompt.strip() + "\n\n" + line).strip()
                applied = True
                changed_spans.append({"field": "system_prompt", "type": "append_instruction", "skill": sid})

        if sid in {"constraint_integration", "constraint_enforcement"}:
            hints = list(payload.get("skill_constraint_hints") or [])
            constraint_hint = "优先满足硬约束，冲突时在 notes 解释取舍。"
            if constraint_hint not in hints:
                hints.append(constraint_hint)
                payload["skill_constraint_hints"] = hints
                applied = True
                changed_spans.append({"field": "input_payload.skill_constraint_hints", "type": "append_hint"})

        if sid in {"risk_assessment", "qa_definition"}:
            payload.setdefault(
                "skill_quality_gate",
                {
                    "must_have_risk_item": True,
                    "must_have_fallback_strategy": True,
                    "must_have_acceptance_criteria": True,
                },
            )
            applied = True
            changed_spans.append({"field": "input_payload.skill_quality_gate", "type": "ensure_defaults"})

        meta = {
            "applied": applied,
            "warnings": warnings,
            "effective_delta": self._compute_delta(
                before={"system_prompt": system_prompt, "input_payload": input_payload},
                after={"system_prompt": prompt, "input_payload": payload},
            ),
            "changed_spans": changed_spans,
            "findings": [],
            "evidence": [],
            "metrics": {},
            "no_effect_reason": None if applied else "prompt executor 未产生可见改动",
            "mode_used": "prompt_only",
            "fallback_used": False,
            "fallback_reason": None,
        }
        return prompt, payload, meta

    def after_generate(
        self,
        *,
        spec: SkillSpec,
        output_payload: dict[str, Any],
        context: SkillRuntimeContext,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        sid = str(spec.id or "").strip().lower()
        source = dict(output_payload or {})
        normalized = self._trim_strings(source)
        applied = normalized != source
        warnings: list[str] = []
        changed_spans: list[dict[str, Any]] = []
        if applied:
            changed_spans.append({"field": "*", "type": "trim_whitespace"})

        if sid in {"text_refinement", "syntax_control", "stylistic_analysis"}:
            source = normalized
            applied = applied or (source != output_payload)
        else:
            source = normalized if applied else source

        if sid in {"constraint_integration", "constraint_enforcement"}:
            status = str(source.get("status") or "").strip().lower()
            notes = str(source.get("notes") or "").strip()
            if status == "failed" and not notes:
                source["notes"] = "存在约束冲突，需按审查建议继续修订。"
                applied = True
                changed_spans.append({"field": "notes", "type": "autofill_failed_constraint_note"})

        if sid in {"fact_checking", "canon_verification", "logic_conflict_detection"}:
            issues = source.get("issues")
            if issues is not None and not isinstance(issues, list):
                warnings.append("issues 字段不是数组，已按空数组处理")
                source["issues"] = []
                applied = True
                changed_spans.append({"field": "issues", "type": "normalize_to_array"})

        meta = {
            "applied": applied,
            "warnings": warnings,
            "effective_delta": self._compute_delta(before=output_payload, after=source),
            "changed_spans": changed_spans,
            "findings": [],
            "evidence": [],
            "metrics": {},
            "no_effect_reason": None if applied else "prompt executor 未产生可见改动",
            "mode_used": "prompt_only",
            "fallback_used": False,
            "fallback_reason": None,
        }
        return source, meta

    @staticmethod
    def _instruction_for_skill(*, skill_id: str, context: SkillRuntimeContext) -> str:
        if skill_id == "creative_writing":
            return "在满足约束前提下，优先使用具体动作、感官细节与场景化表达。"
        if skill_id == "narrative_showing":
            return "遵循 show-don't-tell，尽量用行为与细节传达情绪。"
        if skill_id in {"constraint_integration", "constraint_enforcement"}:
            return "任何硬约束都不能被忽略；若冲突无法解，必须显式写入 notes。"
        if skill_id == "text_refinement":
            return "保持文本简洁，移除解释性废话与重复表达。"
        if skill_id in {"semantic_relevance_scoring", "context_synthesis"}:
            return "优先返回可直接用于下游决策的关键信息。"
        if skill_id in {"risk_assessment", "qa_definition"}:
            return "输出必须包含可执行风险项与验收标准。"
        if context.workflow_type == "revision":
            return "以最小改动修复问题，避免无关重写。"
        return ""

    @staticmethod
    def _trim_strings(payload: Any) -> Any:
        if isinstance(payload, str):
            return payload.strip()
        if isinstance(payload, list):
            return [PolicySkillExecutor._trim_strings(item) for item in payload]
        if isinstance(payload, dict):
            return {key: PolicySkillExecutor._trim_strings(value) for key, value in payload.items()}
        return payload

    @staticmethod
    def _compute_delta(*, before: Any, after: Any) -> int:
        try:
            return (
                0
                if json.dumps(before, ensure_ascii=False, sort_keys=True)
                == json.dumps(after, ensure_ascii=False, sort_keys=True)
                else 1
            )
        except Exception:
            return 1 if before != after else 0


class LocalSkillExecutor:
    def __init__(self, *, adapter_registry: SkillToolAdapterRegistry | None = None) -> None:
        self.adapter_registry = adapter_registry or SkillToolAdapterRegistry()

    def before_generate(
        self,
        *,
        spec: SkillSpec,
        system_prompt: str,
        input_payload: dict[str, Any],
        context: SkillRuntimeContext,
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        payload = copy.deepcopy(dict(input_payload or {}))
        meta = self._run_adapters(spec=spec, phase="before_generate", payload=payload, context=context)
        meta.setdefault("mode_used", "local_code")
        return str(system_prompt or ""), payload, meta

    def after_generate(
        self,
        *,
        spec: SkillSpec,
        output_payload: dict[str, Any],
        context: SkillRuntimeContext,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        payload = copy.deepcopy(dict(output_payload or {}))
        meta = self._run_adapters(spec=spec, phase="after_generate", payload=payload, context=context)
        meta.setdefault("mode_used", "local_code")
        return payload, meta

    def _run_adapters(
        self,
        *,
        spec: SkillSpec,
        phase: str,
        payload: dict[str, Any],
        context: SkillRuntimeContext,
    ) -> dict[str, Any]:
        warnings: list[str] = []
        findings: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        changed_spans: list[dict[str, Any]] = []
        merged_metrics: dict[str, Any] = {}
        no_effect_reason: str | None = None

        adapter_names = [str(item).strip() for item in list(spec.adapters or []) if str(item).strip()]
        if not adapter_names:
            return {
                "applied": False,
                "warnings": [],
                "effective_delta": 0,
                "changed_spans": [],
                "findings": [],
                "evidence": [],
                "metrics": {"adapter_count": 0},
                "no_effect_reason": "skill 未配置 adapters",
            }

        for adapter_name in adapter_names:
            result = self.adapter_registry.run(
                adapter_name=adapter_name,
                spec=spec,
                phase=phase,
                payload=payload,
                context=context,
            )
            warnings.extend([str(item) for item in list(result.warnings) if str(item).strip()])
            findings.extend(list(result.findings or []))
            evidence.extend(list(result.evidence or []))
            changed_spans.extend(list(result.changed_spans or []))
            if result.no_effect_reason and not no_effect_reason:
                no_effect_reason = result.no_effect_reason
            for key, value in dict(result.metrics or {}).items():
                merged_metrics[f"{adapter_name}.{key}"] = value

        applied = bool(changed_spans)
        if not applied and not findings and not evidence:
            no_effect_reason = no_effect_reason or "adapters 已执行但未产生有效痕迹"

        return {
            "applied": applied,
            "warnings": warnings,
            "effective_delta": 1 if (changed_spans or findings or evidence) else 0,
            "changed_spans": changed_spans,
            "findings": findings,
            "evidence": evidence,
            "metrics": {"adapter_count": len(adapter_names), **merged_metrics},
            "no_effect_reason": no_effect_reason,
        }


class HybridSkillExecutor:
    def __init__(
        self,
        *,
        prompt_executor: SkillExecutor | None = None,
        local_executor: SkillExecutor | None = None,
    ) -> None:
        self.prompt_executor = prompt_executor or PolicySkillExecutor()
        self.local_executor = local_executor or LocalSkillExecutor()

    def before_generate(
        self,
        *,
        spec: SkillSpec,
        system_prompt: str,
        input_payload: dict[str, Any],
        context: SkillRuntimeContext,
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        prompt_out, payload_out, prompt_meta = self.prompt_executor.before_generate(
            spec=spec,
            system_prompt=system_prompt,
            input_payload=input_payload,
            context=context,
        )
        _, _, local_meta = self.local_executor.before_generate(
            spec=spec,
            system_prompt=prompt_out,
            input_payload=payload_out,
            context=context,
        )
        meta = _merge_metas(prompt_meta, local_meta, mode_used="hybrid")
        return prompt_out, payload_out, meta

    def after_generate(
        self,
        *,
        spec: SkillSpec,
        output_payload: dict[str, Any],
        context: SkillRuntimeContext,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        payload_out, prompt_meta = self.prompt_executor.after_generate(
            spec=spec,
            output_payload=output_payload,
            context=context,
        )
        _, local_meta = self.local_executor.after_generate(
            spec=spec,
            output_payload=payload_out,
            context=context,
        )
        meta = _merge_metas(prompt_meta, local_meta, mode_used="hybrid")
        return payload_out, meta


class SkillRuntimeEngine:
    """按顺序执行技能 before/after 钩子，并支持 legacy/shadow/active 三模式。"""

    def __init__(
        self,
        *,
        executor: SkillExecutor | None = None,
        prompt_executor: SkillExecutor | None = None,
        local_executor: SkillExecutor | None = None,
        hybrid_executor: SkillExecutor | None = None,
        fail_open: bool = True,
        strict_fail_close: bool = False,
        default_execution_mode: str = "shadow",
        default_fallback_policy: str = "warn_only",
        require_effect_trace: bool = True,
    ) -> None:
        legacy = executor or prompt_executor or PolicySkillExecutor()
        self.legacy_executor = legacy
        self.prompt_executor = legacy
        self.local_executor = local_executor or LocalSkillExecutor()
        self.hybrid_executor = hybrid_executor or HybridSkillExecutor(
            prompt_executor=self.prompt_executor,
            local_executor=self.local_executor,
        )
        self.fail_open = bool(fail_open)
        self.strict_fail_close = bool(strict_fail_close)
        self.default_execution_mode = self._normalize_execution_mode(default_execution_mode)
        self.default_fallback_policy = self._normalize_fallback_policy(default_fallback_policy)
        self.require_effect_trace = bool(require_effect_trace)

    def run_before_generate(
        self,
        *,
        skills: list[SkillSpec],
        system_prompt: str,
        input_payload: dict[str, Any],
        context: SkillRuntimeContext,
    ) -> SkillBeforeResult:
        prompt = str(system_prompt or "")
        payload = copy.deepcopy(dict(input_payload or {}))
        warnings: list[str] = []
        runs: list[SkillRuntimeRun] = []
        total_delta = 0

        for spec in list(skills or []):
            start = perf_counter()
            enabled, execution_mode, fallback_policy, gate_warnings = self._resolve_skill_runtime_flags(spec)
            warnings.extend(gate_warnings)
            run_metrics: dict[str, Any] = {}
            if not enabled:
                runs.append(
                    SkillRuntimeRun(
                        skill_id=spec.id,
                        skill_version=spec.version,
                        phase="before_generate",
                        status="skipped",
                        skill_mode=spec.mode,
                        execution_mode=execution_mode,
                        mode_used=spec.mode,
                        fallback_policy=fallback_policy,
                        no_effect_reason="skill disabled by feature flag",
                        warnings=list(gate_warnings),
                    )
                )
                continue
            try:
                next_prompt, next_payload, meta = self._execute_before_with_mode(
                    spec=spec,
                    execution_mode=execution_mode,
                    fallback_policy=fallback_policy,
                    system_prompt=prompt,
                    input_payload=payload,
                    context=context,
                )
                run_warnings = [str(item) for item in list(meta.get("warnings") or []) if str(item).strip()]
                delta = int(meta.get("effective_delta") or 0)
                prompt = str(next_prompt or "")
                payload = dict(next_payload or {})
                total_delta += delta
                run_metrics = dict(meta.get("metrics") or {})
                run_metrics.setdefault("latency_ms", int((perf_counter() - start) * 1000))
                run = SkillRuntimeRun(
                    skill_id=spec.id,
                    skill_version=spec.version,
                    phase="before_generate",
                    status="success",
                    skill_mode=spec.mode,
                    execution_mode=execution_mode,
                    mode_used=str(meta.get("mode_used") or spec.mode or "prompt_only"),
                    fallback_policy=fallback_policy,
                    fallback_used=bool(meta.get("fallback_used")),
                    fallback_reason=_strip_or_none(meta.get("fallback_reason")),
                    applied=bool(meta.get("applied")),
                    effective_delta=delta,
                    warnings=list(gate_warnings) + run_warnings,
                    changed_spans=_normalize_evidence_list(meta.get("changed_spans")),
                    findings=_normalize_evidence_list(meta.get("findings")),
                    evidence=_normalize_evidence_list(meta.get("evidence")),
                    metrics=run_metrics,
                    no_effect_reason=_strip_or_none(meta.get("no_effect_reason")),
                )
                run = self._enforce_effect_trace(run)
                warnings.extend(run.warnings)
                runs.append(run)
            except Exception as exc:
                elapsed = int((perf_counter() - start) * 1000)
                run_message = f"skill {spec.id} before_generate 失败: {exc}"
                failed_run = SkillRuntimeRun(
                    skill_id=spec.id,
                    skill_version=spec.version,
                    phase="before_generate",
                    status="failed",
                    skill_mode=spec.mode,
                    execution_mode=execution_mode,
                    mode_used=spec.mode,
                    fallback_policy=fallback_policy,
                    warnings=list(gate_warnings) + [str(exc)],
                    metrics={"latency_ms": elapsed},
                    no_effect_reason="skill execution failed",
                )
                runs.append(self._enforce_effect_trace(failed_run))
                warnings.append(run_message)
                if self._should_raise():
                    raise SkillRuntimeError(run_message) from exc

        return SkillBeforeResult(
            system_prompt=prompt,
            input_payload=payload,
            warnings=warnings,
            runs=runs,
            effective_delta=total_delta,
        )

    def run_after_generate(
        self,
        *,
        skills: list[SkillSpec],
        output_payload: dict[str, Any],
        context: SkillRuntimeContext,
    ) -> SkillAfterResult:
        payload = copy.deepcopy(dict(output_payload or {}))
        warnings: list[str] = []
        runs: list[SkillRuntimeRun] = []
        total_delta = 0

        for spec in list(skills or []):
            start = perf_counter()
            enabled, execution_mode, fallback_policy, gate_warnings = self._resolve_skill_runtime_flags(spec)
            warnings.extend(gate_warnings)
            if not enabled:
                runs.append(
                    SkillRuntimeRun(
                        skill_id=spec.id,
                        skill_version=spec.version,
                        phase="after_generate",
                        status="skipped",
                        skill_mode=spec.mode,
                        execution_mode=execution_mode,
                        mode_used=spec.mode,
                        fallback_policy=fallback_policy,
                        no_effect_reason="skill disabled by feature flag",
                        warnings=list(gate_warnings),
                    )
                )
                continue

            try:
                next_payload, meta = self._execute_after_with_mode(
                    spec=spec,
                    execution_mode=execution_mode,
                    fallback_policy=fallback_policy,
                    output_payload=payload,
                    context=context,
                )
                run_warnings = [str(item) for item in list(meta.get("warnings") or []) if str(item).strip()]
                delta = int(meta.get("effective_delta") or 0)
                payload = dict(next_payload or {})
                total_delta += delta
                run_metrics = dict(meta.get("metrics") or {})
                run_metrics.setdefault("latency_ms", int((perf_counter() - start) * 1000))
                run = SkillRuntimeRun(
                    skill_id=spec.id,
                    skill_version=spec.version,
                    phase="after_generate",
                    status="success",
                    skill_mode=spec.mode,
                    execution_mode=execution_mode,
                    mode_used=str(meta.get("mode_used") or spec.mode or "prompt_only"),
                    fallback_policy=fallback_policy,
                    fallback_used=bool(meta.get("fallback_used")),
                    fallback_reason=_strip_or_none(meta.get("fallback_reason")),
                    applied=bool(meta.get("applied")),
                    effective_delta=delta,
                    warnings=list(gate_warnings) + run_warnings,
                    changed_spans=_normalize_evidence_list(meta.get("changed_spans")),
                    findings=_normalize_evidence_list(meta.get("findings")),
                    evidence=_normalize_evidence_list(meta.get("evidence")),
                    metrics=run_metrics,
                    no_effect_reason=_strip_or_none(meta.get("no_effect_reason")),
                )
                run = self._enforce_effect_trace(run)
                warnings.extend(run.warnings)
                runs.append(run)
            except Exception as exc:
                elapsed = int((perf_counter() - start) * 1000)
                run_message = f"skill {spec.id} after_generate 失败: {exc}"
                failed_run = SkillRuntimeRun(
                    skill_id=spec.id,
                    skill_version=spec.version,
                    phase="after_generate",
                    status="failed",
                    skill_mode=spec.mode,
                    execution_mode=execution_mode,
                    mode_used=spec.mode,
                    fallback_policy=fallback_policy,
                    warnings=list(gate_warnings) + [str(exc)],
                    metrics={"latency_ms": elapsed},
                    no_effect_reason="skill execution failed",
                )
                runs.append(self._enforce_effect_trace(failed_run))
                warnings.append(run_message)
                if self._should_raise():
                    raise SkillRuntimeError(run_message) from exc

        return SkillAfterResult(
            output_payload=payload,
            warnings=warnings,
            runs=runs,
            effective_delta=total_delta,
        )

    def _execute_before_with_mode(
        self,
        *,
        spec: SkillSpec,
        execution_mode: str,
        fallback_policy: str,
        system_prompt: str,
        input_payload: dict[str, Any],
        context: SkillRuntimeContext,
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        mode = self._normalize_execution_mode(execution_mode)
        target = self._executor_for_skill_mode(spec.mode)
        legacy = self.prompt_executor

        if mode == "legacy":
            prompt, payload, meta = legacy.before_generate(
                spec=spec,
                system_prompt=system_prompt,
                input_payload=input_payload,
                context=context,
            )
            meta = dict(meta or {})
            meta.setdefault("mode_used", "prompt_only")
            return prompt, payload, meta

        legacy_prompt, legacy_payload, legacy_meta = legacy.before_generate(
            spec=spec,
            system_prompt=system_prompt,
            input_payload=input_payload,
            context=context,
        )
        if mode == "shadow":
            if target is legacy:
                shadow_meta = dict(legacy_meta or {})
                shadow_meta.setdefault("no_effect_reason", "shadow 模式下与 legacy 路径一致")
                shadow_meta["effective_delta"] = int(legacy_meta.get("effective_delta") or 0)
                shadow_meta["applied"] = bool(legacy_meta.get("applied"))
                shadow_meta["mode_used"] = str(spec.mode or "prompt_only")
            else:
                try:
                    _, _, shadow_meta = target.before_generate(
                        spec=spec,
                        system_prompt=system_prompt,
                        input_payload=input_payload,
                        context=context,
                    )
                except Exception as exc:
                    if self._normalize_fallback_policy(fallback_policy) == "hard_fail":
                        raise
                    shadow_meta = {
                        "applied": False,
                        "effective_delta": 0,
                        "warnings": [f"shadow 执行失败，已保留 legacy 结果: {exc}"],
                        "fallback_used": True,
                        "fallback_reason": f"shadow_failed:{type(exc).__name__}",
                        "mode_used": str(spec.mode or "prompt_only"),
                        "no_effect_reason": "shadow 执行失败",
                    }
            shadow_meta = dict(shadow_meta or {})
            shadow_meta.setdefault("mode_used", str(spec.mode or "prompt_only"))
            shadow_meta.setdefault("fallback_used", False)
            shadow_meta.setdefault("fallback_reason", None)
            shadow_meta.setdefault("warnings", [])
            shadow_meta["applied"] = False
            return str(legacy_prompt or ""), dict(legacy_payload or {}), shadow_meta

        # active
        try:
            prompt, payload, meta = target.before_generate(
                spec=spec,
                system_prompt=system_prompt,
                input_payload=input_payload,
                context=context,
            )
            meta = dict(meta or {})
            meta.setdefault("mode_used", str(spec.mode or "prompt_only"))
            return prompt, payload, meta
        except Exception as exc:
            policy = self._normalize_fallback_policy(fallback_policy)
            if policy == "hard_fail":
                raise
            fallback_prompt, fallback_payload, fallback_meta = legacy.before_generate(
                spec=spec,
                system_prompt=system_prompt,
                input_payload=input_payload,
                context=context,
            )
            fallback_meta = dict(fallback_meta or {})
            fallback_meta.setdefault("warnings", [])
            fallback_meta["warnings"] = list(fallback_meta.get("warnings") or []) + [
                f"active 执行失败，回退 legacy: {exc}"
            ]
            fallback_meta["fallback_used"] = True
            fallback_meta["fallback_reason"] = f"active_failed:{type(exc).__name__}"
            fallback_meta["mode_used"] = "prompt_only"
            return str(fallback_prompt or ""), dict(fallback_payload or {}), fallback_meta

    def _execute_after_with_mode(
        self,
        *,
        spec: SkillSpec,
        execution_mode: str,
        fallback_policy: str,
        output_payload: dict[str, Any],
        context: SkillRuntimeContext,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        mode = self._normalize_execution_mode(execution_mode)
        target = self._executor_for_skill_mode(spec.mode)
        legacy = self.prompt_executor

        if mode == "legacy":
            payload, meta = legacy.after_generate(
                spec=spec,
                output_payload=output_payload,
                context=context,
            )
            meta = dict(meta or {})
            meta.setdefault("mode_used", "prompt_only")
            return payload, meta

        legacy_payload, legacy_meta = legacy.after_generate(
            spec=spec,
            output_payload=output_payload,
            context=context,
        )
        if mode == "shadow":
            if target is legacy:
                shadow_meta = dict(legacy_meta or {})
                shadow_meta.setdefault("no_effect_reason", "shadow 模式下与 legacy 路径一致")
                shadow_meta["effective_delta"] = int(legacy_meta.get("effective_delta") or 0)
                shadow_meta["applied"] = bool(legacy_meta.get("applied"))
                shadow_meta["mode_used"] = str(spec.mode or "prompt_only")
            else:
                try:
                    _, shadow_meta = target.after_generate(
                        spec=spec,
                        output_payload=output_payload,
                        context=context,
                    )
                except Exception as exc:
                    if self._normalize_fallback_policy(fallback_policy) == "hard_fail":
                        raise
                    shadow_meta = {
                        "applied": False,
                        "effective_delta": 0,
                        "warnings": [f"shadow 执行失败，已保留 legacy 结果: {exc}"],
                        "fallback_used": True,
                        "fallback_reason": f"shadow_failed:{type(exc).__name__}",
                        "mode_used": str(spec.mode or "prompt_only"),
                        "no_effect_reason": "shadow 执行失败",
                    }
            shadow_meta = dict(shadow_meta or {})
            shadow_meta.setdefault("mode_used", str(spec.mode or "prompt_only"))
            shadow_meta.setdefault("fallback_used", False)
            shadow_meta.setdefault("fallback_reason", None)
            shadow_meta.setdefault("warnings", [])
            shadow_meta["applied"] = False
            return dict(legacy_payload or {}), shadow_meta

        # active
        try:
            payload, meta = target.after_generate(
                spec=spec,
                output_payload=output_payload,
                context=context,
            )
            meta = dict(meta or {})
            meta.setdefault("mode_used", str(spec.mode or "prompt_only"))
            return dict(payload or {}), meta
        except Exception as exc:
            policy = self._normalize_fallback_policy(fallback_policy)
            if policy == "hard_fail":
                raise
            fallback_payload, fallback_meta = legacy.after_generate(
                spec=spec,
                output_payload=output_payload,
                context=context,
            )
            fallback_meta = dict(fallback_meta or {})
            fallback_meta.setdefault("warnings", [])
            fallback_meta["warnings"] = list(fallback_meta.get("warnings") or []) + [
                f"active 执行失败，回退 legacy: {exc}"
            ]
            fallback_meta["fallback_used"] = True
            fallback_meta["fallback_reason"] = f"active_failed:{type(exc).__name__}"
            fallback_meta["mode_used"] = "prompt_only"
            return dict(fallback_payload or {}), fallback_meta

    def _resolve_skill_runtime_flags(
        self,
        spec: SkillSpec,
    ) -> tuple[bool, str, str, list[str]]:
        key = self._skill_env_key(spec)
        warnings: list[str] = []

        enabled = _env_bool(f"SKILL_{key}_ENABLED", True)
        execution_mode = self._normalize_execution_mode(
            _env_str(f"SKILL_{key}_EXECUTION_MODE", str(spec.execution_mode_default or self.default_execution_mode))
        )
        fallback_policy = self._normalize_fallback_policy(
            _env_str(f"SKILL_{key}_FALLBACK_POLICY", str(spec.fallback_policy or self.default_fallback_policy))
        )

        version_pin = _env_str_or_none(f"SKILL_{key}_VERSION")
        if version_pin and version_pin != str(spec.version):
            warnings.append(
                f"skill {spec.id} 版本不匹配（pin={version_pin}, current={spec.version}），按 disabled 处理"
            )
            enabled = False

        return enabled, execution_mode, fallback_policy, warnings

    @staticmethod
    def _skill_env_key(spec: SkillSpec) -> str:
        source = str(spec.feature_flag_key or spec.id or "").strip().upper()
        source = source.replace("-", "_")
        source = source.replace(".", "_")
        source = source.replace("/", "_")
        cleaned = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in source)
        return cleaned or "UNKNOWN_SKILL"

    def _executor_for_skill_mode(self, mode: str | None) -> SkillExecutor:
        normalized = str(mode or "prompt_only").strip().lower()
        if normalized == "local_code":
            return self.local_executor
        if normalized == "hybrid":
            return self.hybrid_executor
        return self.prompt_executor

    @staticmethod
    def _normalize_execution_mode(mode: str | None) -> str:
        value = str(mode or "").strip().lower()
        if value in {"legacy", "shadow", "active"}:
            return value
        return "shadow"

    @staticmethod
    def _normalize_fallback_policy(policy: str | None) -> str:
        value = str(policy or "").strip().lower()
        if value in {"pass_through", "warn_only", "hard_fail"}:
            return value
        return "warn_only"

    def _enforce_effect_trace(self, run: SkillRuntimeRun) -> SkillRuntimeRun:
        if not self.require_effect_trace:
            return run
        has_effect = bool(run.changed_spans or run.findings or run.evidence)
        if has_effect or run.no_effect_reason:
            return run
        warnings = list(run.warnings) + ["skill 缺少有效痕迹，已自动标注 no_effect_reason"]
        return SkillRuntimeRun(
            skill_id=run.skill_id,
            skill_version=run.skill_version,
            phase=run.phase,
            status=run.status,
            skill_mode=run.skill_mode,
            execution_mode=run.execution_mode,
            mode_used=run.mode_used,
            fallback_policy=run.fallback_policy,
            fallback_used=run.fallback_used,
            fallback_reason=run.fallback_reason,
            applied=run.applied,
            effective_delta=run.effective_delta,
            warnings=warnings,
            changed_spans=list(run.changed_spans),
            findings=list(run.findings),
            evidence=list(run.evidence),
            metrics=dict(run.metrics),
            no_effect_reason="executor returned no effect traces",
        )

    def _should_raise(self) -> bool:
        return bool(self.strict_fail_close or not self.fail_open)


def _merge_metas(left: dict[str, Any], right: dict[str, Any], *, mode_used: str) -> dict[str, Any]:
    l = dict(left or {})
    r = dict(right or {})
    warnings = [str(item) for item in list(l.get("warnings") or []) if str(item).strip()]
    warnings.extend([str(item) for item in list(r.get("warnings") or []) if str(item).strip()])
    findings = _normalize_evidence_list(l.get("findings")) + _normalize_evidence_list(r.get("findings"))
    evidence = _normalize_evidence_list(l.get("evidence")) + _normalize_evidence_list(r.get("evidence"))
    changed_spans = _normalize_evidence_list(l.get("changed_spans")) + _normalize_evidence_list(r.get("changed_spans"))
    metrics = dict(l.get("metrics") or {})
    metrics.update(dict(r.get("metrics") or {}))
    applied = bool(l.get("applied") or r.get("applied"))
    no_effect_reason = _strip_or_none(r.get("no_effect_reason")) or _strip_or_none(l.get("no_effect_reason"))
    return {
        "applied": applied,
        "warnings": warnings,
        "effective_delta": int(l.get("effective_delta") or 0) + int(r.get("effective_delta") or 0),
        "changed_spans": changed_spans,
        "findings": findings,
        "evidence": evidence,
        "metrics": metrics,
        "no_effect_reason": no_effect_reason,
        "mode_used": mode_used,
        "fallback_used": bool(l.get("fallback_used") or r.get("fallback_used")),
        "fallback_reason": _strip_or_none(r.get("fallback_reason")) or _strip_or_none(l.get("fallback_reason")),
    }


def _normalize_evidence_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            out.append(dict(item))
        elif isinstance(item, str) and item.strip():
            out.append({"message": item.strip()})
    return out


def _strip_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = str(raw).strip()
    return value or default


def _env_str_or_none(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None
