from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from packages.schemas.registry import SchemaRegistry, SchemaValidationError


SKILL_MODE_DEFAULTS: dict[str, str] = {
    "creative_writing": "prompt_only",
    "narrative_showing": "prompt_only",
    "constraint_integration": "hybrid",
    "text_refinement": "hybrid",
    "character_consistency": "hybrid",
    "world_logic_verification": "hybrid",
    "lore_management": "hybrid",
    "ontology_mapping": "hybrid",
    "constraint_enforcement": "local_code",
    "narrative_structuring": "hybrid",
    "conflict_design": "prompt_only",
    "pacing_control": "hybrid",
    "plot_twisting": "prompt_only",
    "semantic_relevance_scoring": "hybrid",
    "context_synthesis": "hybrid",
    "logical_consistency_check": "hybrid",
    "gap_analysis": "hybrid",
    "task_decomposition": "hybrid",
    "logical_planning": "hybrid",
    "risk_assessment": "hybrid",
    "qa_definition": "hybrid",
    "canon_verification": "hybrid",
    "timeline_tracking": "local_code",
    "logic_conflict_detection": "local_code",
    "fact_checking": "hybrid",
}

SKILL_ADAPTER_DEFAULTS: dict[str, list[str]] = {
    "constraint_integration": ["constraint"],
    "text_refinement": ["constraint"],
    "character_consistency": ["canon"],
    "world_logic_verification": ["constraint", "logic_conflict"],
    "lore_management": ["canon", "context_synthesis"],
    "ontology_mapping": ["canon"],
    "constraint_enforcement": ["constraint"],
    "narrative_structuring": ["plan_graph"],
    "pacing_control": ["context_synthesis"],
    "semantic_relevance_scoring": ["context_synthesis"],
    "context_synthesis": ["context_synthesis"],
    "logical_consistency_check": ["logic_conflict", "canon"],
    "gap_analysis": ["qa_spec"],
    "task_decomposition": ["plan_graph"],
    "logical_planning": ["plan_graph"],
    "risk_assessment": ["qa_spec", "logic_conflict"],
    "qa_definition": ["qa_spec"],
    "canon_verification": ["canon"],
    "timeline_tracking": ["timeline"],
    "logic_conflict_detection": ["logic_conflict"],
    "fact_checking": ["internal_fact_provider", "external_fact_provider"],
}


@dataclass(frozen=True)
class SkillSpec:
    id: str
    name: str
    version: str
    description: str
    tags: list[str]
    mode: str = "prompt_only"
    execution_mode_default: str = "shadow"
    fallback_policy: str = "warn_only"
    adapters: list[str] = field(default_factory=list)
    io_schema_ref: str | None = None
    feature_flag_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SkillRegistry:
    """从 `packages/skills/*/manifest.json` 加载可运行技能定义。"""

    def __init__(
        self,
        *,
        root: str | Path,
        schema_registry: SchemaRegistry | None = None,
        strict: bool = True,
        degrade_mode: bool = False,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.schema_registry = schema_registry
        self.strict = bool(strict)
        self.degrade_mode = bool(degrade_mode)
        self._skills: dict[str, SkillSpec] = {}
        self.reload()

    def reload(self) -> None:
        self._skills.clear()
        if not self.root.exists():
            return

        for path in sorted(self.root.glob("*/manifest.json")):
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)

            if self.schema_registry is not None:
                self.schema_registry.validate(
                    schema_ref="tools/skill_manifest.schema.json",
                    payload=payload,
                    strict=self.strict,
                    degrade_mode=self.degrade_mode,
                )

            spec = SkillSpec(
                id=str(payload.get("id") or path.parent.name).strip(),
                name=str(payload.get("name") or path.parent.name).strip(),
                version=str(payload.get("version") or "v1").strip(),
                description=str(payload.get("description") or "").strip(),
                tags=[str(item).strip() for item in list(payload.get("tags") or []) if str(item).strip()],
                mode=self._normalize_mode(payload.get("mode"), skill_id=str(payload.get("id") or path.parent.name)),
                execution_mode_default=self._normalize_execution_mode(payload.get("execution_mode_default")),
                fallback_policy=self._normalize_fallback_policy(payload.get("fallback_policy")),
                adapters=self._normalize_adapters(payload.get("adapters"), skill_id=str(payload.get("id") or path.parent.name)),
                io_schema_ref=self._normalize_optional_text(payload.get("io_schema_ref")),
                feature_flag_key=self._normalize_optional_text(payload.get("feature_flag_key")),
                metadata=self._build_metadata(payload),
            )
            if not spec.id:
                raise SchemaValidationError(f"技能 manifest 缺少 id: {path}")
            self._skills[spec.id] = spec

    def get(self, skill_id: str) -> SkillSpec | None:
        return self._skills.get(skill_id)

    def list_ids(self) -> list[str]:
        return sorted(self._skills.keys())

    def resolve_many(
        self,
        skill_ids: list[str],
        *,
        overrides: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[list[SkillSpec], list[str]]:
        resolved: list[SkillSpec] = []
        warnings: list[str] = []
        override_map = dict(overrides or {})
        for skill_id in skill_ids:
            sid = str(skill_id or "").strip()
            if not sid:
                continue
            spec = self.get(sid)
            if spec is None:
                message = f"未找到技能: {sid}"
                if self.strict and not self.degrade_mode:
                    raise SchemaValidationError(message)
                warnings.append(message)
                continue
            override = override_map.get(spec.id)
            if isinstance(override, dict) and override:
                spec = self._apply_override(spec, override)
            resolved.append(spec)
        return resolved, warnings

    def _apply_override(self, spec: SkillSpec, override: dict[str, Any]) -> SkillSpec:
        updated = spec
        if "mode" in override:
            updated = replace(updated, mode=self._normalize_mode(override.get("mode"), skill_id=spec.id))
        if "execution_mode" in override or "execution_mode_default" in override:
            value = override.get("execution_mode_default", override.get("execution_mode"))
            updated = replace(updated, execution_mode_default=self._normalize_execution_mode(value))
        if "fallback_policy" in override:
            updated = replace(updated, fallback_policy=self._normalize_fallback_policy(override.get("fallback_policy")))
        if "adapters" in override:
            updated = replace(updated, adapters=self._normalize_adapters(override.get("adapters"), skill_id=spec.id))
        if "feature_flag_key" in override:
            updated = replace(updated, feature_flag_key=self._normalize_optional_text(override.get("feature_flag_key")))
        if "io_schema_ref" in override:
            updated = replace(updated, io_schema_ref=self._normalize_optional_text(override.get("io_schema_ref")))
        return updated

    @staticmethod
    def _build_metadata(payload: dict[str, Any]) -> dict[str, Any]:
        copied = dict(payload or {})
        for key in (
            "id",
            "name",
            "version",
            "description",
            "tags",
            "mode",
            "execution_mode_default",
            "fallback_policy",
            "adapters",
            "io_schema_ref",
            "feature_flag_key",
        ):
            copied.pop(key, None)
        return copied

    @staticmethod
    def _normalize_mode(raw: Any, *, skill_id: str) -> str:
        value = str(raw or "").strip().lower()
        if value in {"prompt_only", "local_code", "hybrid"}:
            return value
        fallback = SKILL_MODE_DEFAULTS.get(str(skill_id or "").strip(), "prompt_only")
        return str(fallback or "prompt_only")

    @staticmethod
    def _normalize_execution_mode(raw: Any) -> str:
        value = str(raw or "").strip().lower()
        if value in {"legacy", "shadow", "active"}:
            return value
        return "shadow"

    @staticmethod
    def _normalize_fallback_policy(raw: Any) -> str:
        value = str(raw or "").strip().lower()
        if value in {"pass_through", "warn_only", "hard_fail"}:
            return value
        return "warn_only"

    @staticmethod
    def _normalize_adapters(raw: Any, *, skill_id: str) -> list[str]:
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        defaults = list(SKILL_ADAPTER_DEFAULTS.get(str(skill_id or "").strip(), []))
        return [str(item).strip() for item in defaults if str(item).strip()]

    @staticmethod
    def _normalize_optional_text(raw: Any) -> str | None:
        text = str(raw or "").strip()
        return text or None
