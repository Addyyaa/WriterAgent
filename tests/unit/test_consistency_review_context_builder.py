from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from packages.workflows.chapter_generation.context_provider import StoryConstraintContext
from packages.workflows.consistency_review.context_builder import (
    build_review_context_slice,
    build_review_contract,
    build_review_evidence_pack,
    build_review_focus,
    characters_mentioned_in_text,
    collect_review_fetch_allowlist,
)
from packages.workflows.consistency_review.retrieval_dedup import (
    dedupe_retrieval_bundle_against_evidence,
)


class TestConsistencyReviewContextBuilder(unittest.TestCase):
    def test_characters_mentioned_longest_first(self) -> None:
        chars = [{"name": "李"}, {"name": "李四"}]
        text = "李四到了。"
        self.assertEqual(characters_mentioned_in_text(chars, text), ["李四"])

    def test_review_focus_timeline_not_unbounded(self) -> None:
        ctx = StoryConstraintContext(
            chapters=[],
            characters=[{"name": "甲", "id": "1"}],
            world_entries=[],
            timeline_events=[
                {"id": "t-future", "chapter_no": 99, "event_title": "终局", "event_desc": "x"},
                {"id": "t-now", "chapter_no": 1, "event_title": "开端", "event_desc": "开端之事"},
            ],
            foreshadowings=[],
        )
        focus = build_review_focus(
            chapter_text="甲在开端出现。",
            chapter_no=1,
            story_context=ctx,
            rule_issues=[],
        )
        self.assertIn("t-now", focus["focus_timeline_event_ids"] or [])
        self.assertNotIn("t-future", focus["focus_timeline_event_ids"])

    def test_slice_timeline_past_only_by_default(self) -> None:
        ctx = StoryConstraintContext(
            chapters=[{"id": "c1", "chapter_no": 1, "title": "T", "summary": "S", "content_preview": ""}],
            characters=[],
            world_entries=[],
            timeline_events=[
                {"id": "a", "chapter_no": 1, "event_title": "E1", "event_desc": "d1"},
                {"id": "b", "chapter_no": 50, "event_title": "E50", "event_desc": "d50"},
            ],
            foreshadowings=[],
        )
        focus = build_review_focus(
            chapter_text="正文",
            chapter_no=1,
            story_context=ctx,
            rule_issues=[],
        )
        sl = build_review_context_slice(
            chapter_text="正文",
            chapter_no=1,
            story_context=ctx,
            review_focus=focus,
            rule_issues=[],
        )
        ids = {str(x.get("id")) for x in sl["timeline_events"]}
        self.assertIn("a", ids)
        self.assertNotIn("b", ids)

    def test_review_contract_shape(self) -> None:
        c = build_review_contract()
        self.assertIn("audit_dimensions", c)
        self.assertIn("allowed_severities", c)
        self.assertIn("evidence_policy", c)
        self.assertIn("review_evidence_pack", c["evidence_policy"])

    def test_evidence_pack_and_allowlist(self) -> None:
        ctx = StoryConstraintContext(
            chapters=[],
            characters=[
                {
                    "id": "char-1",
                    "name": "甲",
                    "role_type": "配角",
                    "faction": None,
                    "profile_json": {"abilities": "隐身"},
                    "inventory_json": {},
                    "wealth_json": {},
                    "effective_inventory_json": {},
                    "effective_wealth_json": {},
                }
            ],
            world_entries=[
                {
                    "id": "w1",
                    "entry_type": "rule",
                    "title": "高塔禁火",
                    "content": "城内禁用明火。",
                    "metadata_json": {},
                }
            ],
            timeline_events=[
                {
                    "id": "t1",
                    "chapter_no": 1,
                    "event_title": "开端",
                    "event_desc": "故事开始",
                }
            ],
            foreshadowings=[
                {
                    "id": "f1",
                    "setup_chapter_no": 1,
                    "setup_text": "伏笔甲",
                    "payoff_chapter_no": 5,
                    "payoff_text": "",
                    "expected_payoff": "",
                    "status": "open",
                }
            ],
        )
        focus = build_review_focus(
            chapter_text="甲在高塔禁火规则下行动，开端事件已发生，伏笔甲浮现。",
            chapter_no=1,
            story_context=ctx,
            rule_issues=[],
        )
        sl = build_review_context_slice(
            chapter_text="甲在高塔禁火规则下行动，开端事件已发生，伏笔甲浮现。",
            chapter_no=1,
            story_context=ctx,
            review_focus=focus,
            rule_issues=[],
        )
        pack = build_review_evidence_pack(
            chapter_text="甲在高塔禁火规则下行动，开端事件已发生，伏笔甲浮现。",
            chapter_no=1,
            story_context=ctx,
            review_focus=focus,
        )
        self.assertTrue(any("甲" in str(x.get("name")) for x in pack["characters_detail"]))
        allow = collect_review_fetch_allowlist(
            review_focus=focus,
            review_context_slice=sl,
            evidence_pack=pack,
        )
        self.assertIn("char-1", allow)
        self.assertIn("w1", allow)
        self.assertIn("t1", allow)
        self.assertIn("f1", allow)

    def test_chapter_evidence_rows_have_no_full_content(self) -> None:
        ctx = StoryConstraintContext(
            chapters=[
                {
                    "id": "c1",
                    "chapter_no": 1,
                    "title": "当前",
                    "summary": "摘要一",
                    "content_preview": "预览很长" * 40,
                },
                {
                    "id": "c0",
                    "chapter_no": 0,
                    "title": "前章",
                    "summary": "前摘",
                    "content_preview": "前预览",
                },
            ],
            characters=[],
            world_entries=[],
            timeline_events=[],
            foreshadowings=[],
        )
        focus = build_review_focus(
            chapter_text="x",
            chapter_no=1,
            story_context=ctx,
            rule_issues=[],
        )
        sl = build_review_context_slice(
            chapter_text="x",
            chapter_no=1,
            story_context=ctx,
            review_focus=focus,
            rule_issues=[],
        )
        for row in sl["chapters"]:
            self.assertNotIn("content", row)
            self.assertLessEqual(len(str(row.get("content_preview") or "")), 200)

    def test_primary_pov_role_type_hint(self) -> None:
        ctx = StoryConstraintContext(
            chapters=[],
            characters=[
                {"id": "p1", "name": "张三", "role_type": "主角"},
                {"id": "x1", "name": "李四", "role_type": "配角"},
            ],
            world_entries=[],
            timeline_events=[],
            foreshadowings=[],
        )
        focus = build_review_focus(
            chapter_text="张三与李四对话。",
            chapter_no=1,
            story_context=ctx,
            rule_issues=[],
        )
        pov = focus.get("primary_pov_character") or {}
        self.assertEqual(pov.get("inference"), "role_type_hint")
        self.assertEqual(pov.get("name"), "张三")

    def test_focus_assets_inventory(self) -> None:
        ctx = StoryConstraintContext(
            chapters=[],
            characters=[
                {
                    "id": "c1",
                    "name": "王五",
                    "role_type": "配角",
                    "effective_inventory_json": {"古剑": "青铜剑一把"},
                },
            ],
            world_entries=[],
            timeline_events=[],
            foreshadowings=[],
        )
        focus = build_review_focus(
            chapter_text="王五拔出古剑。",
            chapter_no=1,
            story_context=ctx,
            rule_issues=[],
        )
        assets = list(focus.get("focus_assets") or [])
        self.assertTrue(any(a.get("asset_key") == "古剑" for a in assets))

    def test_retrieval_dedup_removes_overlap(self) -> None:
        duplicate = (
            "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda "
            "mu nu xi omicron pi rho sigma tau upsilon phi chi psi omega"
        )
        rc = {
            "world_entries": [{"title": "t", "content": duplicate}],
            "chapters": [],
            "characters": [],
            "timeline_events": [],
            "foreshadowings": [],
        }
        bundle = {
            "summary": {"key_facts": [], "current_states": []},
            "items": [
                {
                    "source": "memory_fact",
                    "score": 0.9,
                    "text": duplicate,
                }
            ],
            "meta": {},
        }
        out = dedupe_retrieval_bundle_against_evidence(bundle, rc)
        self.assertLess(len(out.get("items") or []), len(bundle.get("items") or []))


if __name__ == "__main__":
    unittest.main()
