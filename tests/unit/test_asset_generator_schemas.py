"""资产生成输出 schema 与 OpenAICompatible 校验逻辑的一致性测试。"""

from __future__ import annotations

import unittest

from packages.llm.text_generation.openai_compatible import OpenAICompatibleTextProvider
from packages.schemas.asset_generator_outputs import (
    ASSET_GENERATOR_OUTPUT_SCHEMAS,
    asset_generator_schema_bundle,
)


class AssetGeneratorSchemasTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = OpenAICompatibleTextProvider(
            api_key="test-key",
            model="gpt-4.1-mini",
            base_url="https://api.openai.com/v1",
            compat_mode="full",
        )

    def test_bundle_matches_registry_keys(self) -> None:
        for asset_type in ASSET_GENERATOR_OUTPUT_SCHEMAS:
            bundle = asset_generator_schema_bundle(asset_type)
            self.assertIs(bundle.response_schema, ASSET_GENERATOR_OUTPUT_SCHEMAS[asset_type])
            self.assertEqual(bundle.response_schema_name, bundle.function_name)
            self.assertTrue(bundle.function_description)

    def test_unknown_type_raises(self) -> None:
        with self.assertRaises(KeyError):
            asset_generator_schema_bundle("not_a_real_asset")

    def test_sample_payloads_pass_validation(self) -> None:
        samples = {
            "outline": {
                "title": "卷一",
                "content": "阶段一：…",
                "promise": "承诺",
                "central_question": "悬念？",
            },
            "characters": {
                "characters": [
                    {
                        "name": "A",
                        "role_type": "protagonist",
                        "narrative_function": "catalyst",
                        "faction": "X",
                        "age": 30,
                        "wound": "w",
                        "want": "w1",
                        "need": "n1",
                        "personality": "p",
                        "motivation": "m",
                    }
                ],
                "tension_pairs": [
                    {
                        "characters": ["A", "B"],
                        "surface_relation": "盟友",
                        "hidden_tension": "竞争",
                    }
                ],
            },
            "world_entries": {
                "entries": [
                    {
                        "title": "法则",
                        "entry_type": "rule",
                        "content": "限制与代价" * 5,
                        "narrative_purpose": "制造困境",
                    }
                ],
                "cross_references": [{"from": "法则", "to": "地点", "relation": "约束"}],
            },
            "timeline": {
                "events": [
                    {
                        "chapter_no": 1,
                        "title": "开端",
                        "event_type": "inciting",
                        "description": "事件" * 10,
                        "location": "城",
                        "characters_involved": "A,B",
                        "state_change": "不可逆",
                    }
                ],
                "causal_chain": "A→B→C",
            },
            "foreshadowing": {
                "items": [
                    {
                        "planted_chapter": 1,
                        "type": "structural",
                        "planted_content": "细节",
                        "surface_meaning": "无害",
                        "true_meaning": "关键",
                        "expected_payoff": "揭示",
                        "payoff_chapter": 5,
                        "emotional_target": "震惊",
                    }
                ],
                "strategy_note": "短线为主",
            },
        }
        for asset_type, payload in samples.items():
            schema = ASSET_GENERATOR_OUTPUT_SCHEMAS[asset_type]
            errors = self.provider._validate_response_schema(payload=payload, schema=schema)
            self.assertEqual(errors, [], f"{asset_type}: {errors}")


if __name__ == "__main__":
    unittest.main()
