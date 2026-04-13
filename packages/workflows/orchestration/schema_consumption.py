from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packages.schemas.registry import SchemaValidationError


ALLOWED_CONSUMED_BY = {"code", "downstream_prompt", "audit_only"}


@dataclass(frozen=True)
class FieldConsumptionDeclaration:
    path: str
    consumed_by: str
    rationale: str | None = None
    retire_by: str | None = None


@dataclass(frozen=True)
class SchemaConsumptionContract:
    role_id: str
    declarations: dict[str, FieldConsumptionDeclaration | str | dict[str, Any]]
    source_path: str | None = None


@dataclass(frozen=True)
class SchemaFieldInfo:
    path: str
    required: bool = False
    deprecated: bool = False


@dataclass(frozen=True)
class SchemaConsumptionCoverage:
    required_paths: list[str]
    covered_paths: list[str]
    uncovered_paths: list[str]
    declaration_paths: list[str] = field(default_factory=list)
    invalid_declaration_paths: list[str] = field(default_factory=list)
    deprecated_paths: list[str] = field(default_factory=list)
    deprecated_unowned_paths: list[str] = field(default_factory=list)
    deprecated_missing_retire_by_paths: list[str] = field(default_factory=list)
    consumed_by_breakdown: dict[str, int] = field(default_factory=dict)

    @property
    def required_count(self) -> int:
        return len(self.required_paths)

    @property
    def covered_count(self) -> int:
        return len(self.covered_paths)

    @property
    def dead_required_count(self) -> int:
        return len(self.uncovered_paths)

    @property
    def covered_rate(self) -> float:
        if not self.required_paths:
            return 1.0
        return float(len(self.covered_paths)) / float(len(self.required_paths))

    @property
    def declaration_count(self) -> int:
        return len(self.declaration_paths)

    @property
    def invalid_declaration_count(self) -> int:
        return len(self.invalid_declaration_paths)

    @property
    def deprecated_unowned_count(self) -> int:
        return len(self.deprecated_unowned_paths)

    @property
    def deprecated_missing_retire_by_count(self) -> int:
        return len(self.deprecated_missing_retire_by_paths)


class SchemaConsumptionValidator:
    """Schema 字段消费契约校验器。"""

    def __init__(
        self,
        *,
        strict: bool = False,
        degrade_mode: bool = False,
        enforce_deprecated_governance: bool = False,
    ) -> None:
        self.strict = bool(strict)
        self.degrade_mode = bool(degrade_mode)
        self.enforce_deprecated_governance = bool(enforce_deprecated_governance)

    def load_contract(self, *, role_id: str, contract_path: Path | None) -> SchemaConsumptionContract:
        if contract_path is None or not contract_path.exists():
            return SchemaConsumptionContract(role_id=role_id, declarations={}, source_path=None)

        payload = json.loads(contract_path.read_text(encoding="utf-8"))
        declarations = self._parse_declarations(payload)
        return SchemaConsumptionContract(
            role_id=role_id,
            declarations=declarations,
            source_path=str(contract_path),
        )

    def validate(
        self,
        *,
        role_id: str,
        output_schema: dict[str, Any] | None,
        contract: SchemaConsumptionContract,
    ) -> tuple[SchemaConsumptionCoverage, list[str]]:
        schema = output_schema or {}
        field_infos = self.field_infos(schema)
        all_paths = set(field_infos.keys())
        required_paths = sorted(path for path, info in field_infos.items() if info.required)
        deprecated_paths = sorted(path for path, info in field_infos.items() if info.deprecated)

        covered_paths: list[str] = []
        uncovered_paths: list[str] = []
        warnings: list[str] = []
        blocking_warnings: list[str] = []

        declaration_paths = sorted(contract.declarations.keys())
        invalid_declaration_paths: list[str] = []
        consumed_by_breakdown: dict[str, int] = {kind: 0 for kind in sorted(ALLOWED_CONSUMED_BY)}

        for path in declaration_paths:
            declaration = self._resolve_declaration(path=path, value=contract.declarations.get(path))
            if declaration is None:
                invalid_declaration_paths.append(path)
                warning = f"角色 {role_id} 的字段消费声明无效: {path}"
                warnings.append(warning)
                blocking_warnings.append(warning)
                continue
            if declaration.consumed_by not in ALLOWED_CONSUMED_BY:
                invalid_declaration_paths.append(path)
                warning = (
                    f"角色 {role_id} 的字段消费标记非法: {path}={declaration.consumed_by} "
                    f"(允许: {sorted(ALLOWED_CONSUMED_BY)})"
                )
                warnings.append(warning)
                blocking_warnings.append(warning)
                continue
            if path not in all_paths:
                invalid_declaration_paths.append(path)
                warning = f"角色 {role_id} 的字段消费声明未命中 schema 字段: {path}"
                warnings.append(warning)
                blocking_warnings.append(warning)
                continue
            consumed_by_breakdown[declaration.consumed_by] = consumed_by_breakdown.get(declaration.consumed_by, 0) + 1

        for path in required_paths:
            declaration = self._resolve_declaration(path=path, value=contract.declarations.get(path))
            consumed_by = str(getattr(declaration, "consumed_by", "") or "").strip()
            if not consumed_by:
                uncovered_paths.append(path)
                warning = f"角色 {role_id} 的 required 字段未声明消费: {path}"
                warnings.append(warning)
                blocking_warnings.append(warning)
                continue
            if consumed_by not in ALLOWED_CONSUMED_BY:
                uncovered_paths.append(path)
                warning = (
                    f"角色 {role_id} 的字段消费标记非法: {path}={consumed_by} "
                    f"(允许: {sorted(ALLOWED_CONSUMED_BY)})"
                )
                warnings.append(warning)
                blocking_warnings.append(warning)
                continue
            covered_paths.append(path)

        deprecated_unowned_paths: list[str] = []
        deprecated_missing_retire_by_paths: list[str] = []
        for path in deprecated_paths:
            declaration = self._resolve_declaration(path=path, value=contract.declarations.get(path))
            if declaration is None:
                deprecated_unowned_paths.append(path)
                warnings.append(f"角色 {role_id} 的 deprecated 字段未声明治理语义: {path}")
                continue
            consumed_by = str(declaration.consumed_by or "").strip()
            if consumed_by in {"downstream_prompt", "audit_only"} and not str(declaration.retire_by or "").strip():
                deprecated_missing_retire_by_paths.append(path)
                warning = (
                    f"角色 {role_id} 的 deprecated 字段缺少 retire_by: {path}"
                    f"（consumed_by={consumed_by}）"
                )
                warnings.append(warning)
                if self.enforce_deprecated_governance:
                    blocking_warnings.append(warning)

        coverage = SchemaConsumptionCoverage(
            required_paths=required_paths,
            covered_paths=sorted(set(covered_paths)),
            uncovered_paths=sorted(set(uncovered_paths)),
            declaration_paths=declaration_paths,
            invalid_declaration_paths=sorted(set(invalid_declaration_paths)),
            deprecated_paths=deprecated_paths,
            deprecated_unowned_paths=sorted(set(deprecated_unowned_paths)),
            deprecated_missing_retire_by_paths=sorted(set(deprecated_missing_retire_by_paths)),
            consumed_by_breakdown=consumed_by_breakdown,
        )
        if blocking_warnings and self.strict and not self.degrade_mode:
            joined = "\n".join(blocking_warnings)
            raise SchemaValidationError(f"schema consumption contract 校验失败:\n{joined}")
        return coverage, warnings

    @classmethod
    def required_paths(cls, schema: dict[str, Any]) -> list[str]:
        infos = cls.field_infos(schema)
        return sorted(path for path, info in infos.items() if info.required)

    @classmethod
    def field_infos(cls, schema: dict[str, Any]) -> dict[str, SchemaFieldInfo]:
        out: dict[str, SchemaFieldInfo] = {}
        cls._collect_field_infos(schema=schema, prefix="", out=out, parent_deprecated=False)
        return out

    @classmethod
    def _collect_field_infos(
        cls,
        *,
        schema: dict[str, Any],
        prefix: str,
        out: dict[str, SchemaFieldInfo],
        parent_deprecated: bool,
    ) -> None:
        if not isinstance(schema, dict):
            return

        schema_type = schema.get("type")
        candidates = [schema_type] if isinstance(schema_type, str) else list(schema_type or [])
        is_object = bool(isinstance(schema.get("properties"), dict) or "object" in candidates)
        is_array = bool(isinstance(schema.get("items"), dict) or "array" in candidates)

        current_deprecated = bool(parent_deprecated or bool(schema.get("deprecated")))

        if is_object:
            properties = dict(schema.get("properties") or {})
            required_set = {
                str(item).strip()
                for item in list(schema.get("required") or [])
                if str(item or "").strip()
            }
            for field_name, child_schema in properties.items():
                path = f"{prefix}.{field_name}" if prefix else str(field_name)
                child_deprecated = bool(current_deprecated)
                if isinstance(child_schema, dict) and child_schema.get("deprecated"):
                    child_deprecated = True
                out[path] = SchemaFieldInfo(
                    path=path,
                    required=str(field_name) in required_set,
                    deprecated=child_deprecated,
                )
                if isinstance(child_schema, dict):
                    cls._collect_field_infos(
                        schema=child_schema,
                        prefix=path,
                        out=out,
                        parent_deprecated=child_deprecated,
                    )

        if is_array and prefix:
            items_schema = schema.get("items")
            if isinstance(items_schema, dict):
                cls._collect_field_infos(
                    schema=items_schema,
                    prefix=f"{prefix}[]",
                    out=out,
                    parent_deprecated=current_deprecated,
                )

    @staticmethod
    def _resolve_declaration(
        *,
        path: str,
        value: FieldConsumptionDeclaration | str | dict[str, Any] | None,
    ) -> FieldConsumptionDeclaration | None:
        if isinstance(value, FieldConsumptionDeclaration):
            return value
        if isinstance(value, dict):
            return SchemaConsumptionValidator._parse_declaration_value(path=path, value=value)
        if isinstance(value, str):
            consumed_by = str(value or "").strip()
            if not consumed_by:
                return None
            return FieldConsumptionDeclaration(path=path, consumed_by=consumed_by)
        return None

    @classmethod
    def _parse_declarations(cls, payload: Any) -> dict[str, FieldConsumptionDeclaration]:
        if not isinstance(payload, dict):
            return {}

        candidate = payload.get("consumed_by")
        if not isinstance(candidate, dict):
            candidate = payload.get("fields")
        if not isinstance(candidate, dict):
            candidate = payload

        out: dict[str, FieldConsumptionDeclaration] = {}
        for key, value in dict(candidate).items():
            path = str(key or "").strip()
            if not path:
                continue
            declaration = cls._parse_declaration_value(path=path, value=value)
            if declaration is None:
                continue
            out[path] = declaration
        return out

    @staticmethod
    def _parse_declaration_value(path: str, value: Any) -> FieldConsumptionDeclaration | None:
        if isinstance(value, dict):
            consumed_by = str(value.get("consumed_by") or value.get("kind") or "").strip()
            rationale = str(value.get("rationale") or value.get("reason") or "").strip() or None
            retire_by = str(value.get("retire_by") or value.get("sunset_at") or "").strip() or None
        else:
            consumed_by = str(value or "").strip()
            rationale = None
            retire_by = None

        if not consumed_by:
            return None
        return FieldConsumptionDeclaration(
            path=path,
            consumed_by=consumed_by,
            rationale=rationale,
            retire_by=retire_by,
        )
