from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SchemaValidationError(ValueError):
    """Schema 校验失败（严格模式）。"""


@dataclass(frozen=True)
class SchemaValidationIssue:
    path: str
    message: str

    def format(self) -> str:
        return f"{self.path}: {self.message}"


class SchemaRegistry:
    """从 `packages/schemas` 加载并执行轻量 JSON Schema 校验。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self._schemas: dict[str, dict[str, Any]] = {}
        self.reload()

    def reload(self) -> None:
        self._schemas.clear()
        if not self.root.exists():
            return
        for path in self.root.rglob("*.schema.json"):
            rel = path.relative_to(self.root).as_posix()
            with path.open("r", encoding="utf-8") as f:
                self._schemas[rel] = json.load(f)

    def list_refs(self) -> list[str]:
        return sorted(self._schemas.keys())

    def get(self, schema_ref: str) -> dict[str, Any] | None:
        return self._schemas.get(schema_ref)

    def validate(
        self,
        *,
        schema_ref: str,
        payload: Any,
        strict: bool = True,
        degrade_mode: bool = False,
    ) -> list[str]:
        schema = self.get(schema_ref)
        if schema is None:
            message = f"schema 不存在: {schema_ref}"
            if strict and not degrade_mode:
                raise SchemaValidationError(message)
            return [message]

        issues: list[SchemaValidationIssue] = []
        self._validate_node(schema=schema, payload=payload, path="$", issues=issues)
        messages = [item.format() for item in issues]
        if messages and strict and not degrade_mode:
            joined = "\n".join(messages)
            raise SchemaValidationError(f"schema 校验失败({schema_ref}):\n{joined}")
        return messages

    def validate_inline(
        self,
        *,
        schema: dict[str, Any],
        payload: Any,
        strict: bool = True,
        degrade_mode: bool = False,
    ) -> list[str]:
        """对内存中的 JSON Schema 字典校验 payload（用于 inline 角色 schema）。"""
        issues: list[SchemaValidationIssue] = []
        self._validate_node(schema=schema, payload=payload, path="$", issues=issues)
        messages = [item.format() for item in issues]
        if messages and strict and not degrade_mode:
            joined = "\n".join(messages)
            raise SchemaValidationError(f"schema 校验失败(inline):\n{joined}")
        return messages

    def _validate_node(
        self,
        *,
        schema: dict[str, Any],
        payload: Any,
        path: str,
        issues: list[SchemaValidationIssue],
    ) -> None:
        expected_type = schema.get("type")
        if expected_type is not None:
            if not self._is_type(payload, expected_type):
                issues.append(
                    SchemaValidationIssue(
                        path=path,
                        message=f"type 不匹配，期望 {expected_type}，实际 {type(payload).__name__}",
                    )
                )
                return

        if "enum" in schema and payload not in list(schema.get("enum") or []):
            issues.append(SchemaValidationIssue(path=path, message=f"值不在枚举中: {payload!r}"))

        if isinstance(payload, str):
            min_length = schema.get("minLength")
            if isinstance(min_length, int) and len(payload) < min_length:
                issues.append(
                    SchemaValidationIssue(path=path, message=f"长度不足，最小 {min_length}")
                )

        if isinstance(payload, (int, float)) and not isinstance(payload, bool):
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            if isinstance(minimum, (int, float)) and payload < minimum:
                issues.append(
                    SchemaValidationIssue(path=path, message=f"小于最小值 {minimum}")
                )
            if isinstance(maximum, (int, float)) and payload > maximum:
                issues.append(
                    SchemaValidationIssue(path=path, message=f"大于最大值 {maximum}")
                )

        if isinstance(payload, dict):
            properties = schema.get("properties") or {}
            required = schema.get("required") or []
            for name in required:
                if name not in payload:
                    issues.append(
                        SchemaValidationIssue(path=path, message=f"缺少必填字段: {name}")
                    )

            for key, value in payload.items():
                key_path = f"{path}.{key}"
                if key in properties and isinstance(properties[key], dict):
                    self._validate_node(
                        schema=properties[key],
                        payload=value,
                        path=key_path,
                        issues=issues,
                    )
                    continue

                additional = schema.get("additionalProperties", True)
                if additional is False:
                    issues.append(SchemaValidationIssue(path=key_path, message="不允许额外字段"))
                elif isinstance(additional, dict):
                    self._validate_node(
                        schema=additional,
                        payload=value,
                        path=key_path,
                        issues=issues,
                    )
            return

        if isinstance(payload, list):
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for idx, item in enumerate(payload):
                    self._validate_node(
                        schema=item_schema,
                        payload=item,
                        path=f"{path}[{idx}]",
                        issues=issues,
                    )

    @staticmethod
    def _is_type(payload: Any, expected_type: str | list[str]) -> bool:
        candidates = [expected_type] if isinstance(expected_type, str) else list(expected_type)
        for item in candidates:
            if item == "object" and isinstance(payload, dict):
                return True
            if item == "array" and isinstance(payload, list):
                return True
            if item == "string" and isinstance(payload, str):
                return True
            if item == "boolean" and isinstance(payload, bool):
                return True
            if item == "integer" and isinstance(payload, int) and not isinstance(payload, bool):
                return True
            if item == "number" and isinstance(payload, (int, float)) and not isinstance(payload, bool):
                return True
            if item == "null" and payload is None:
                return True
        return False
