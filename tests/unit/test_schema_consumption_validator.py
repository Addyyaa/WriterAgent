from __future__ import annotations

import unittest

from packages.schemas.registry import SchemaValidationError
from packages.workflows.orchestration.schema_consumption import (
    FieldConsumptionDeclaration,
    SchemaConsumptionContract,
    SchemaConsumptionValidator,
)


class TestSchemaConsumptionValidator(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = {
            "type": "object",
            "required": ["chapter", "segments"],
            "properties": {
                "chapter": {
                    "type": "object",
                    "required": ["title", "content"],
                    "properties": {
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                    },
                },
                "segments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["beat_id", "content"],
                        "properties": {
                            "beat_id": {"type": "integer"},
                            "content": {"type": "string"},
                        },
                    },
                },
            },
        }

    def test_required_paths_collect_nested(self) -> None:
        paths = SchemaConsumptionValidator.required_paths(self.schema)
        self.assertIn("chapter", paths)
        self.assertIn("chapter.title", paths)
        self.assertIn("segments", paths)
        self.assertIn("segments[].beat_id", paths)

    def test_validate_raises_when_missing_required_contract(self) -> None:
        validator = SchemaConsumptionValidator(strict=True, degrade_mode=False)
        contract = SchemaConsumptionContract(role_id="writer_agent", declarations={"chapter": "code"})
        with self.assertRaises(SchemaValidationError):
            validator.validate(role_id="writer_agent", output_schema=self.schema, contract=contract)

    def test_validate_passes_when_all_required_covered(self) -> None:
        validator = SchemaConsumptionValidator(strict=True, degrade_mode=False)
        contract = SchemaConsumptionContract(
            role_id="writer_agent",
            declarations={
                "chapter": "code",
                "chapter.title": "code",
                "chapter.content": "code",
                "segments": "code",
                "segments[].beat_id": "code",
                "segments[].content": "code",
            },
        )
        coverage, warnings = validator.validate(
            role_id="writer_agent",
            output_schema=self.schema,
            contract=contract,
        )
        self.assertEqual(coverage.dead_required_count, 0)
        self.assertFalse(warnings)

    def test_validate_supports_structured_declaration_and_deprecated_retire_by(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "main": {"type": "string"},
                "legacy": {"type": "string", "deprecated": True},
            },
            "required": ["main"],
        }
        validator = SchemaConsumptionValidator(strict=True, degrade_mode=False)
        contract = SchemaConsumptionContract(
            role_id="writer_agent",
            declarations={
                "main": FieldConsumptionDeclaration(path="main", consumed_by="code"),
                "legacy": FieldConsumptionDeclaration(
                    path="legacy",
                    consumed_by="audit_only",
                    retire_by="2026-12-31",
                ),
            },
        )
        coverage, warnings = validator.validate(
            role_id="writer_agent",
            output_schema=schema,
            contract=contract,
        )
        self.assertEqual(coverage.dead_required_count, 0)
        self.assertEqual(coverage.deprecated_missing_retire_by_count, 0)
        self.assertEqual(coverage.deprecated_unowned_count, 0)
        self.assertFalse(warnings)

    def test_validate_warns_when_deprecated_missing_retire_by(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "main": {"type": "string"},
                "legacy": {"type": "string", "deprecated": True},
            },
            "required": ["main"],
        }
        validator = SchemaConsumptionValidator(strict=True, degrade_mode=False)
        contract = SchemaConsumptionContract(
            role_id="writer_agent",
            declarations={
                "main": "code",
                "legacy": {"consumed_by": "audit_only"},
            },
        )
        coverage, warnings = validator.validate(
            role_id="writer_agent",
            output_schema=schema,
            contract=contract,
        )
        self.assertEqual(coverage.deprecated_missing_retire_by_count, 1)
        self.assertEqual(coverage.deprecated_unowned_count, 0)
        self.assertTrue(any("retire_by" in str(item) for item in warnings))


if __name__ == "__main__":
    unittest.main(verbosity=2)
