from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from packages.core.utils import parse_simple_yaml
from packages.schemas.registry import SchemaRegistry, SchemaValidationError
from packages.skills.registry import SkillRegistry, SkillSpec
from packages.workflows.orchestration.schema_consumption import (
    SchemaConsumptionCoverage,
    SchemaConsumptionValidator,
)
from packages.workflows.orchestration.types import AgentProfile, AgentStrategy


class AgentRegistry:
    """加载 apps/agents 下的角色配置并提供运行时解析能力。"""

    def __init__(
        self,
        *,
        root: str | Path,
        schema_registry: SchemaRegistry,
        skill_registry: SkillRegistry,
        strict: bool = True,
        degrade_mode: bool = False,
        consumption_strict: bool | None = None,
        consumption_degrade_mode: bool | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.schema_registry = schema_registry
        self.skill_registry = skill_registry
        self.strict = bool(strict)
        self.degrade_mode = bool(degrade_mode)
        self._consumption_validator = SchemaConsumptionValidator(
            strict=self.strict if consumption_strict is None else bool(consumption_strict),
            degrade_mode=self.degrade_mode
            if consumption_degrade_mode is None
            else bool(consumption_degrade_mode),
        )
        self._profiles: dict[str, AgentProfile] = {}
        self._consumption_coverage: dict[str, SchemaConsumptionCoverage] = {}
        self._shared_local_tools_markdown: str = ""
        self._shared_local_tools_catalog: list[dict[str, Any]] = []
        self.reload()

    def reload(self) -> None:
        self._profiles.clear()
        self._consumption_coverage.clear()
        self._shared_local_tools_markdown = ""
        self._shared_local_tools_catalog = []
        shared_dir = self.root / "_shared"
        md_path = shared_dir / "local_data_tools.md"
        catalog_path = shared_dir / "local_data_tools_catalog.json"
        if md_path.is_file():
            self._shared_local_tools_markdown = md_path.read_text(encoding="utf-8").strip()
        if catalog_path.is_file():
            raw = json.loads(catalog_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                self._shared_local_tools_catalog = [x for x in raw if isinstance(x, dict)]
        if not self.root.exists():
            return

        required_files = ("prompt.md", "strategy.yaml", "output_schema.json", "skills.yaml")
        for path in sorted(self.root.iterdir()):
            if not path.is_dir():
                continue
            if not all((path / f).exists() for f in required_files):
                continue
            profile = self._load_profile(path)
            self._profiles[profile.role_id] = profile

    def list_role_ids(self) -> list[str]:
        return sorted(self._profiles.keys())

    def get(self, role_id: str) -> AgentProfile | None:
        return self._profiles.get(role_id)

    def local_data_tools_catalog(self) -> list[dict[str, Any]]:
        """与 apps/agents/_shared/local_data_tools_catalog.json 一致，供请求 payload 使用。"""
        return list(self._shared_local_tools_catalog)

    def resolve(
        self,
        *,
        role_id: str,
        workflow_type: str,
        step_key: str,
        strategy_mode: str | None = None,
    ) -> tuple[AgentProfile, AgentStrategy, list[SkillSpec], list[str]]:
        profile = self.get(role_id)
        if profile is None:
            raise SchemaValidationError(f"未找到角色配置: {role_id}")

        mode = self._resolve_mode(
            role_id=role_id,
            workflow_type=workflow_type,
            step_key=step_key,
            strategy_mode=strategy_mode,
        )
        strategy = profile.strategy.resolve_mode(mode)
        skills, warnings = self.skill_registry.resolve_many(
            profile.skills,
            overrides=dict(profile.skill_overrides or {}),
        )
        return profile, strategy, skills, warnings

    def _load_profile(self, path: Path) -> AgentProfile:
        prompt_path = path / "prompt.md"
        strategy_path = path / "strategy.yaml"
        output_schema_path = path / "output_schema.json"
        skills_path = path / "skills.yaml"
        consumption_path = path / "consumption.json"

        for required in (prompt_path, strategy_path, output_schema_path, skills_path):
            if not required.exists():
                raise SchemaValidationError(f"角色配置缺少文件: {required}")

        prompt = prompt_path.read_text(encoding="utf-8").strip()
        if self._shared_local_tools_markdown:
            prompt = f"{prompt.rstrip()}\n\n{self._shared_local_tools_markdown}"
        strategy_data = parse_simple_yaml(strategy_path.read_text(encoding="utf-8"))
        output_schema_data = json.loads(output_schema_path.read_text(encoding="utf-8"))
        skills_data = parse_simple_yaml(skills_path.read_text(encoding="utf-8"))

        self.schema_registry.validate(
            schema_ref="agents/agent_strategy.schema.json",
            payload=strategy_data,
            strict=self.strict,
            degrade_mode=self.degrade_mode,
        )

        schema_ref, schema_version, inline_schema = self._parse_output_schema(
            role_id=path.name,
            output_schema_data=output_schema_data,
        )

        schema_for_consumption = dict(inline_schema or {})
        if not schema_for_consumption:
            loaded = self.schema_registry.get(schema_ref)
            if isinstance(loaded, dict):
                schema_for_consumption = dict(loaded)

        consumption_contract = self._consumption_validator.load_contract(
            role_id=path.name,
            contract_path=consumption_path if consumption_path.exists() else None,
        )
        consumption_coverage, consumption_warnings = self._consumption_validator.validate(
            role_id=path.name,
            output_schema=schema_for_consumption,
            contract=consumption_contract,
        )
        self._consumption_coverage[path.name] = consumption_coverage

        skill_ids, skill_overrides = self._parse_skills_config(skills_data)

        profile_payload = {
            "role_id": path.name,
            "prompt": prompt,
            "strategy": strategy_data,
            "skills": skill_ids,
            "schema_ref": schema_ref,
            "schema_version": schema_version,
        }
        self.schema_registry.validate(
            schema_ref="agents/agent_profile.schema.json",
            payload=profile_payload,
            strict=self.strict,
            degrade_mode=self.degrade_mode,
        )

        strategy = AgentStrategy(
            version=str(strategy_data.get("version") or "v1"),
            temperature=float(strategy_data.get("temperature") or 0.3),
            max_tokens=int(strategy_data.get("max_tokens") or 4096),
            style=str(strategy_data.get("style") or "default"),
            mode=str(strategy_data.get("mode") or "default"),
            mode_strategies=dict(strategy_data.get("mode_strategies") or {}),
        )
        return AgentProfile(
            role_id=path.name,
            prompt=prompt,
            strategy=strategy,
            skills=skill_ids,
            skill_overrides=skill_overrides,
            schema_ref=schema_ref,
            schema_version=schema_version,
            output_schema=inline_schema,
            consumption_contract={
                key: str(
                    getattr(value, "consumed_by", value)
                )
                for key, value in dict(consumption_contract.declarations).items()
            },
            consumption_warnings=list(consumption_warnings),
        )

    @staticmethod
    def _parse_skills_config(skills_data: dict[str, Any]) -> tuple[list[str], dict[str, dict[str, Any]]]:
        skill_ids: list[str] = []
        skill_overrides: dict[str, dict[str, Any]] = {}

        for item in list(skills_data.get("skills") or []):
            if isinstance(item, dict):
                sid = str(item.get("id") or item.get("skill_id") or item.get("name") or "").strip()
                if not sid:
                    continue
                skill_ids.append(sid)
                override_payload = dict(item)
                for key in ("id", "skill_id", "name"):
                    override_payload.pop(key, None)
                if override_payload:
                    skill_overrides[sid] = override_payload
                continue

            sid = str(item or "").strip()
            if sid:
                skill_ids.append(sid)

        raw_overrides = skills_data.get("skill_overrides")
        if isinstance(raw_overrides, dict):
            for key, value in raw_overrides.items():
                sid = str(key or "").strip()
                if not sid:
                    continue
                if isinstance(value, dict):
                    base = dict(skill_overrides.get(sid) or {})
                    base.update(dict(value))
                    skill_overrides[sid] = base

        # 去重并保持顺序。
        unique_ids: list[str] = []
        seen: set[str] = set()
        for sid in skill_ids:
            if sid in seen:
                continue
            seen.add(sid)
            unique_ids.append(sid)
        return unique_ids, skill_overrides

    def consumption_coverage_summary(self) -> dict[str, Any]:
        per_role: dict[str, dict[str, Any]] = {}
        total_required = 0
        total_covered = 0
        total_dead = 0
        total_deprecated_unowned = 0
        total_deprecated_missing_retire_by = 0
        total_invalid_declarations = 0
        consumed_by_totals = {"code": 0, "downstream_prompt": 0, "audit_only": 0}
        for role_id, coverage in self._consumption_coverage.items():
            total_required += int(coverage.required_count)
            total_covered += int(coverage.covered_count)
            total_dead += int(coverage.dead_required_count)
            total_deprecated_unowned += int(coverage.deprecated_unowned_count)
            total_deprecated_missing_retire_by += int(coverage.deprecated_missing_retire_by_count)
            total_invalid_declarations += int(coverage.invalid_declaration_count)
            breakdown = dict(coverage.consumed_by_breakdown or {})
            for kind in list(consumed_by_totals.keys()):
                consumed_by_totals[kind] = int(consumed_by_totals[kind]) + int(breakdown.get(kind) or 0)
            per_role[role_id] = {
                "required_count": int(coverage.required_count),
                "covered_count": int(coverage.covered_count),
                "dead_required_count": int(coverage.dead_required_count),
                "covered_rate": float(coverage.covered_rate),
                "uncovered_paths": list(coverage.uncovered_paths),
                "declaration_count": int(coverage.declaration_count),
                "invalid_declaration_count": int(coverage.invalid_declaration_count),
                "invalid_declaration_paths": list(coverage.invalid_declaration_paths),
                "deprecated_count": len(list(coverage.deprecated_paths or [])),
                "deprecated_unowned_count": int(coverage.deprecated_unowned_count),
                "deprecated_unowned_paths": list(coverage.deprecated_unowned_paths),
                "deprecated_missing_retire_by_count": int(coverage.deprecated_missing_retire_by_count),
                "deprecated_missing_retire_by_paths": list(coverage.deprecated_missing_retire_by_paths),
                "consumed_by_breakdown": breakdown,
            }
        covered_rate = 1.0 if total_required <= 0 else float(total_covered) / float(total_required)
        return {
            "required_count": int(total_required),
            "covered_count": int(total_covered),
            "dead_required_count": int(total_dead),
            "covered_rate": float(covered_rate),
            "deprecated_unowned_count": int(total_deprecated_unowned),
            "deprecated_missing_retire_by_count": int(total_deprecated_missing_retire_by),
            "invalid_declaration_count": int(total_invalid_declarations),
            "consumed_by_breakdown": consumed_by_totals,
            "per_role": per_role,
        }

    def _parse_output_schema(
        self,
        *,
        role_id: str,
        output_schema_data: dict[str, Any],
    ) -> tuple[str, str, dict[str, Any] | None]:
        if not isinstance(output_schema_data, dict):
            raise SchemaValidationError(f"角色 {role_id} 的 output_schema.json 必须是 JSON 对象")

        explicit_ref = str(output_schema_data.get("schema_ref") or "").strip()
        schema_version = str(output_schema_data.get("schema_version") or "v1").strip() or "v1"
        if explicit_ref:
            return explicit_ref, schema_version, None

        # 兼容“完整 JSON Schema 直接写在 output_schema.json”的写法。
        if self._looks_like_json_schema(output_schema_data):
            inline_ref = f"inline://{role_id}/output_schema"
            return inline_ref, schema_version, dict(output_schema_data)

        default_ref = "agents/agent_step_output.schema.json"
        return default_ref, schema_version, None

    @staticmethod
    def _looks_like_json_schema(payload: dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        if isinstance(payload.get("type"), str):
            return True
        if isinstance(payload.get("properties"), dict):
            return True
        if isinstance(payload.get("required"), list):
            return True
        return False

    @staticmethod
    def _resolve_mode(
        *,
        role_id: str,
        workflow_type: str,
        step_key: str,
        strategy_mode: str | None,
    ) -> str:
        explicit = str(strategy_mode or "").strip().lower()
        if explicit:
            return explicit

        normalized_workflow = str(workflow_type or "").strip().lower()
        normalized_step = str(step_key or "").strip().lower()
        if role_id == "writer_agent":
            if normalized_workflow == "revision" or normalized_step in {"writer_revision", "revision"}:
                return "revision"
            return "draft"
        return "default"
