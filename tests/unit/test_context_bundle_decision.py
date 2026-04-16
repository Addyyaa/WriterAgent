"""context_bundle 决策字段双写与读取单测。"""

from __future__ import annotations

import unittest

from packages.core.context_bundle_decision import (
    DECISION_CONTEXT_KEYS,
    mirror_context_bundle_lists_from_summary,
    mirror_decision_fields_to_bundle_root,
    mirror_key_facts_to_bundle_root,
    read_decision_fields_from_bundle,
    read_key_facts_from_bundle,
)


class TestContextBundleDecision(unittest.TestCase):
    def test_mirror_decision_copies_lists_not_same_reference(self) -> None:
        summary_lists = {
            "confirmed_facts": ["a"],
            "current_states": ["b"],
            "supporting_evidence": ["c"],
            "conflicts": ["d"],
            "information_gaps": ["e"],
        }
        bundle: dict = {"summary": dict(summary_lists)}
        mirror_decision_fields_to_bundle_root(bundle)
        self.assertEqual(bundle["confirmed_facts"], ["a"])
        self.assertIsNot(bundle["confirmed_facts"], bundle["summary"]["confirmed_facts"])

    def test_read_prefers_root_when_present(self) -> None:
        bundle = {
            "summary": {"confirmed_facts": ["from_summary"], "current_states": []},
            "confirmed_facts": ["from_root"],
        }
        d = read_decision_fields_from_bundle(bundle)
        self.assertEqual(d["confirmed_facts"], ["from_root"])
        self.assertEqual(d["current_states"], [])

    def test_read_falls_back_to_summary_when_root_missing(self) -> None:
        bundle = {
            "summary": {
                "confirmed_facts": ["s"],
                "current_states": ["st"],
                "supporting_evidence": ["se"],
                "conflicts": [],
                "information_gaps": ["g"],
            }
        }
        d = read_decision_fields_from_bundle(bundle)
        for k in DECISION_CONTEXT_KEYS:
            self.assertIn(k, d)
        self.assertEqual(d["confirmed_facts"], ["s"])
        self.assertEqual(d["information_gaps"], ["g"])

    def test_read_root_empty_list_does_not_fallback(self) -> None:
        """根键存在且为 [] 时以根为准（新合同），不回退 summary。"""
        bundle = {
            "summary": {"confirmed_facts": ["old"]},
            "confirmed_facts": [],
        }
        d = read_decision_fields_from_bundle(bundle)
        self.assertEqual(d["confirmed_facts"], [])

    def test_read_none_on_root_falls_back_to_summary(self) -> None:
        bundle = {
            "summary": {"confirmed_facts": ["fallback"]},
            "confirmed_facts": None,
        }
        d = read_decision_fields_from_bundle(bundle)
        self.assertEqual(d["confirmed_facts"], ["fallback"])

    def test_read_root_only_no_summary_subset(self) -> None:
        bundle = {
            "summary": {},
            "confirmed_facts": ["r"],
            "current_states": ["r2"],
            "supporting_evidence": [],
            "conflicts": [{"x": 1}],
            "information_gaps": ["gap"],
        }
        d = read_decision_fields_from_bundle(bundle)
        self.assertEqual(d["confirmed_facts"], ["r"])
        self.assertEqual(d["conflicts"], [{"x": 1}])

    def test_mirror_key_facts(self) -> None:
        bundle = {"summary": {"key_facts": ["kf"]}}
        mirror_key_facts_to_bundle_root(bundle)
        self.assertEqual(bundle["key_facts"], ["kf"])
        self.assertIsNot(bundle["key_facts"], bundle["summary"]["key_facts"])

    def test_read_key_facts_root_preferred(self) -> None:
        bundle = {"summary": {"key_facts": ["s"]}, "key_facts": ["r"]}
        self.assertEqual(read_key_facts_from_bundle(bundle), ["r"])

    def test_mirror_context_bundle_lists_from_summary_all(self) -> None:
        bundle = {
            "summary": {
                "key_facts": ["k"],
                "confirmed_facts": ["c"],
                "current_states": [],
                "supporting_evidence": [],
                "conflicts": [],
                "information_gaps": [],
            }
        }
        mirror_context_bundle_lists_from_summary(bundle)
        self.assertEqual(bundle["key_facts"], ["k"])
        self.assertEqual(bundle["confirmed_facts"], ["c"])


if __name__ == "__main__":
    unittest.main()
