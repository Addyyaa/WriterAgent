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
    sanitize_consistency_retrieval_bundle,
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
            review_context_slice=sl,
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

    def test_review_contract_includes_passed_and_severity_policy(self) -> None:
        c = build_review_contract()
        self.assertIn("passed", c.get("allowed_severities") or [])
        self.assertIn("severity_policy", c)

    def test_evidence_pack_profile_audit_speech_arc(self) -> None:
        ctx = StoryConstraintContext(
            chapters=[],
            characters=[
                {
                    "id": "c1",
                    "name": "甲",
                    "role_type": "主角",
                    "faction": "北港",
                    "profile_json": {"personality": "谨慎", "core_beliefs": "不信权威"},
                    "speech_style_json": {"habits": "句尾常说「罢了」"},
                    "arc_status_json": {"stage": "第二幕"},
                    "inventory_json": {},
                    "wealth_json": {},
                    "effective_inventory_json": {},
                    "effective_wealth_json": {},
                }
            ],
            world_entries=[],
            timeline_events=[],
            foreshadowings=[],
        )
        focus = build_review_focus(
            chapter_text="甲说道罢了。",
            chapter_no=1,
            story_context=ctx,
            rule_issues=[],
        )
        sl = build_review_context_slice(
            chapter_text="甲说道罢了。",
            chapter_no=1,
            story_context=ctx,
            review_focus=focus,
            rule_issues=[],
        )
        pack = build_review_evidence_pack(
            chapter_text="甲说道罢了。",
            chapter_no=1,
            story_context=ctx,
            review_focus=focus,
            review_context_slice=sl,
        )
        det = (pack.get("characters_detail") or [{}])[0]
        pa = det.get("profile_audit") or {}
        self.assertIn("speech_habits", pa)
        self.assertIn("arc_stage", pa)
        self.assertIn("personality", pa)

    def test_sanitize_drops_outline_like_summary_lines(self) -> None:
        bundle = {
            "summary": {
                "key_facts": ["角色甲在第三章学会剑术。"],
                "confirmed_facts": [],
                "current_states": [],
                "supporting_evidence": [
                    "第一章 开端\n第二章 发展\n第三章 转折\n第四章 高潮\n第五章 结局",
                ],
                "information_gaps": [],
            },
            "items": [],
            "meta": {},
        }
        out = sanitize_consistency_retrieval_bundle(bundle)
        se = list((out.get("summary") or {}).get("supporting_evidence") or [])
        self.assertEqual(se, [])

    def test_slim_character_always_includes_inventory_cap(self) -> None:
        ctx = StoryConstraintContext(
            chapters=[],
            characters=[
                {
                    "id": "x1",
                    "name": "乙",
                    "role_type": "配角",
                    "faction": None,
                    "age": 30,
                    "profile_json": {"quirks": "摸鼻子"},
                    "speech_style_json": {},
                    "arc_status_json": {},
                    "inventory_json": {"匕首": "铁制", "地图": "旧纸"},
                    "wealth_json": {"铜钱": "十二枚"},
                    "effective_inventory_json": {"匕首": "铁制", "地图": "旧纸"},
                    "effective_wealth_json": {"铜钱": "十二枚"},
                }
            ],
            world_entries=[],
            timeline_events=[],
            foreshadowings=[],
        )
        focus = build_review_focus(
            chapter_text="乙沉默。",
            chapter_no=1,
            story_context=ctx,
            rule_issues=[],
        )
        sl = build_review_context_slice(
            chapter_text="乙沉默。",
            chapter_no=1,
            story_context=ctx,
            review_focus=focus,
            rule_issues=[],
        )
        ch0 = (sl.get("characters") or [{}])[0]
        self.assertIn("匕首", str(ch0.get("effective_inventory_json") or {}))
        self.assertIn("profile_audit", ch0)
        self.assertIn("structured_brief", (ch0.get("profile_audit") or {}))

    def test_sanitize_retrieval_truncates_and_dedupes(self) -> None:
        long_outline = "大纲节" * 200
        bundle = {
            "summary": {
                "key_facts": ["事实甲段落够长用于测试", "事实甲段落够长用于测试"],
                "current_states": [],
                "confirmed_facts": [],
                "supporting_evidence": ["支持性证据段落够长一", "支持性证据段落够长一"],
                "conflicts": [],
                "information_gaps": [],
            },
            "items": [
                {"source": "outline", "text": long_outline},
                {"source": "outline", "text": long_outline + "x"},
                {"source": "memory", "text": "独立记忆片段用于章节审查测试足够长"},
            ],
            "meta": {},
        }
        out = sanitize_consistency_retrieval_bundle(bundle)
        kf = list((out.get("summary") or {}).get("key_facts") or [])
        self.assertEqual(len(kf), 1)
        items = list(out.get("items") or [])
        self.assertLessEqual(len(items), 3)
        self.assertTrue(any("记忆" in str(i.get("text") or "") for i in items))


if __name__ == "__main__":
    unittest.main()
