from __future__ import annotations

import unittest

from packages.skills.registry import SkillSpec
from packages.workflows.chapter_generation.service import ChapterGenerationWorkflowService


def _skill(sid: str) -> SkillSpec:
    return SkillSpec(id=sid, name=sid, version="v1", description="d", tags=[])


class TestChapterGenerationTuning(unittest.TestCase):
    def test_filter_draft_skills_for_long_form(self) -> None:
        skills = [_skill("creative_writing"), _skill("text_refinement")]
        kept, warnings = ChapterGenerationWorkflowService._filter_draft_skills(
            skills=skills,
            target_words=3300,
        )
        self.assertEqual([s.id for s in kept], ["creative_writing"])
        self.assertTrue(warnings)
        self.assertIn("text_refinement", warnings[0])

    def test_filter_draft_skills_for_short_form(self) -> None:
        skills = [_skill("creative_writing"), _skill("text_refinement")]
        kept, warnings = ChapterGenerationWorkflowService._filter_draft_skills(
            skills=skills,
            target_words=1200,
        )
        self.assertEqual([s.id for s in kept], ["creative_writing", "text_refinement"])
        self.assertEqual(warnings, [])

    def test_retry_contract_contains_explicit_bounds(self) -> None:
        contract = ChapterGenerationWorkflowService._word_count_retry_contract(
            attempt_index=1,
            max_attempts=5,
            effective_chars=1350,
            low=2970,
            high=3630,
            target_words=3300,
            issue="too_short",
            previous_raw_char_len=2400,
        )
        self.assertEqual(contract["must_reach_effective_chars_at_least"], 2970)
        self.assertEqual(contract["must_not_exceed_effective_chars"], 3630)
        self.assertEqual(contract["previous_raw_char_len"], 2400)
        self.assertIn("输出结束前必须先自检非空白字符数是否达标", contract["instruction_cn"])
        self.assertIn("原始字符数", contract["instruction_cn"])

    def test_schema_soft_min_below_business_low(self) -> None:
        w_low = 2970
        first = ChapterGenerationWorkflowService._schema_min_content_len_for_attempt(
            w_low=w_low,
            word_attempt=0,
            progressive_enabled=True,
        )
        self.assertLess(first, w_low)
        later = ChapterGenerationWorkflowService._schema_min_content_len_for_attempt(
            w_low=w_low,
            word_attempt=4,
            progressive_enabled=True,
        )
        self.assertLessEqual(later, first)

    def test_should_use_short_draft_expander(self) -> None:
        self.assertFalse(
            ChapterGenerationWorkflowService._should_use_short_draft_expander(
                enabled=False,
                attempt_index=2,
                trigger_attempt=3,
                issue="too_short",
                previous_content="已有正文",
                no_progress_streak=0,
            )
        )
        self.assertFalse(
            ChapterGenerationWorkflowService._should_use_short_draft_expander(
                enabled=True,
                attempt_index=1,
                trigger_attempt=3,
                issue="too_short",
                previous_content="已有正文",
                no_progress_streak=0,
            )
        )
        self.assertFalse(
            ChapterGenerationWorkflowService._should_use_short_draft_expander(
                enabled=True,
                attempt_index=2,
                trigger_attempt=3,
                issue="too_long",
                previous_content="已有正文",
                no_progress_streak=0,
            )
        )
        self.assertTrue(
            ChapterGenerationWorkflowService._should_use_short_draft_expander(
                enabled=True,
                attempt_index=2,
                trigger_attempt=3,
                issue="too_short",
                previous_content="已有正文",
                no_progress_streak=0,
            )
        )
        self.assertFalse(
            ChapterGenerationWorkflowService._should_use_short_draft_expander(
                enabled=True,
                attempt_index=2,
                trigger_attempt=3,
                issue="too_short",
                previous_content="已有正文",
                no_progress_streak=1,
            )
        )
        self.assertFalse(
            ChapterGenerationWorkflowService._should_use_short_draft_expander(
                enabled=True,
                attempt_index=2,
                trigger_attempt=3,
                issue="too_short",
                previous_content="已有正文",
                no_progress_streak=0,
                enforce_word_count=False,
            )
        )

    def test_response_schema_content_min_patch(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "content": {"type": "string", "minLength": 10},
                "chapter": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "minLength": 5},
                    },
                },
            },
        }
        patched = ChapterGenerationWorkflowService._build_response_schema_with_content_min(
            schema,
            min_content_len=2970,
        )
        self.assertEqual(schema["properties"]["content"]["minLength"], 10)
        self.assertEqual(patched["properties"]["content"]["minLength"], 2970)
        self.assertEqual(patched["properties"]["chapter"]["properties"]["content"]["minLength"], 2970)


if __name__ == "__main__":
    unittest.main()
