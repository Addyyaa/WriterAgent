from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from packages.workflows.chapter_generation.context_provider import StoryConstraintContext
from packages.workflows.context_views import build_story_assets_from_context


class TestContextViewsStoryAssets(unittest.TestCase):
    def test_summary_first_strips_heavy_profile(self) -> None:
        ctx = StoryConstraintContext(
            chapters=[
                {
                    "id": "c1",
                    "chapter_no": 1,
                    "title": "T",
                    "summary": "S" * 500,
                    "content_preview": "p" * 300,
                }
            ],
            characters=[
                {
                    "id": "u1",
                    "name": "角色甲",
                    "role_type": "主角",
                    "faction": "东境",
                    "profile_json": {"personality": "谨慎" * 40, "abilities": "剑术"},
                    "inventory_json": {"刀": "1"},
                    "wealth_json": {"金币": "10"},
                    "effective_inventory_json": {"刀": "1"},
                    "effective_wealth_json": {"金币": "10"},
                    "chapter_no_for_assets": 1,
                }
            ],
            world_entries=[
                {
                    "id": "w1",
                    "entry_type": "loc",
                    "title": "旧城",
                    "content": "城墙很高。" * 50,
                    "metadata_json": {"forbidden_terms": ["飞"]},
                }
            ],
            timeline_events=[
                {
                    "id": "t1",
                    "chapter_no": 2,
                    "event_title": "未来",
                    "event_desc": "之后的事",
                },
                {
                    "id": "t0",
                    "chapter_no": 1,
                    "event_title": "现在",
                    "event_desc": "当前",
                },
            ],
            foreshadowings=[],
        )
        out = build_story_assets_from_context(ctx, chapter_no=1, summary_first=True)
        self.assertEqual(out.get("asset_view_mode"), "summary_first")
        ch0 = out["characters"][0]
        self.assertNotIn("profile_json", ch0)
        self.assertIn("profile_snippet", ch0)
        self.assertIn("inventory_keys", ch0)
        w0 = out["world_entries"][0]
        self.assertIn("content_snippet", w0)
        self.assertNotIn("content", w0)
        t_ids = {str(x.get("id")) for x in out["timeline_events"]}
        self.assertIn("t0", t_ids)
        self.assertNotIn("t1", t_ids)

    def test_full_mode_preserves_lists(self) -> None:
        ctx = StoryConstraintContext(
            chapters=[],
            characters=[{"id": "1", "name": "A", "profile_json": {"x": 1}}],
            world_entries=[],
            timeline_events=[],
            foreshadowings=[],
        )
        out = build_story_assets_from_context(ctx, chapter_no=None, summary_first=False)
        self.assertEqual(out.get("asset_view_mode"), "full")
        self.assertIn("profile_json", out["characters"][0])


if __name__ == "__main__":
    unittest.main()
