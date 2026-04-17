"""修订 issue -> 检索槽位映射。"""

from __future__ import annotations

import unittest

from packages.workflows.revision.issue_retrieval_policy import (
    preferred_tools_for_slots,
    revision_slots_for_issues,
    slots_for_issue_category,
)


class TestIssueRetrievalPolicy(unittest.TestCase):
    def test_character_union_world(self) -> None:
        issues = [
            {"category": "character"},
            {"category": "worldview"},
        ]
        slots = revision_slots_for_issues(issues)
        self.assertIn("character", slots)
        self.assertIn("world_rule", slots)
        self.assertIn("conflict_evidence", slots)
        self.assertLessEqual(len(slots), 8)

    def test_timeline_includes_story_scene(self) -> None:
        self.assertIn("story_state", slots_for_issue_category("timeline"))

    def test_inventory_slots(self) -> None:
        s = slots_for_issue_category("item_consistency")
        self.assertIn("character_inventory", s)

    def test_style_adds_preference(self) -> None:
        self.assertIn("style_preference", slots_for_issue_category("style"))

    def test_empty_issues_defaults_conflict_evidence(self) -> None:
        self.assertEqual(revision_slots_for_issues([]), ["conflict_evidence"])

    def test_preferred_tools_nonempty(self) -> None:
        tools = preferred_tools_for_slots(["character", "world_rule"])
        self.assertTrue(tools)
        self.assertIn("get_character_inventory", tools)
        self.assertIn("search_project_memory_vectors", tools)


if __name__ == "__main__":
    unittest.main()
