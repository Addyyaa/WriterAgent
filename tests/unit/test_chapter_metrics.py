from __future__ import annotations

import unittest

from packages.core.utils.chapter_metrics import (
    chapter_context_token_budget,
    chapter_max_output_tokens,
    chapter_word_count_allowed_range,
    chapter_word_count_violation_message,
    count_fiction_word_units,
)


class ChapterMetricsTests(unittest.TestCase):
    def test_count_fiction_word_units(self) -> None:
        self.assertEqual(count_fiction_word_units("  你好 \n 世界  "), 4)

    def test_allowed_range(self) -> None:
        low, high = chapter_word_count_allowed_range(1000)
        self.assertEqual(low, 900)
        self.assertEqual(high, 1100)

    def test_violation_message_short_vs_long(self) -> None:
        low, high = 2970, 3630
        short = chapter_word_count_violation_message(
            effective_chars=1356, target_words=3300, low=low, high=high
        )
        self.assertIn("低于", short)
        self.assertIn("最小值 2970", short)
        self.assertNotIn("高于", short)
        long = chapter_word_count_violation_message(
            effective_chars=4000, target_words=3300, low=low, high=high
        )
        self.assertIn("高于", long)
        self.assertIn("最大值 3630", long)
        self.assertNotIn("低于", long)

    def test_max_output_tokens_monotonic(self) -> None:
        self.assertGreaterEqual(chapter_max_output_tokens(5000), chapter_max_output_tokens(3000))

    def test_context_budget_bounds(self) -> None:
        self.assertGreaterEqual(chapter_context_token_budget(8000), 3200)
        self.assertLessEqual(chapter_context_token_budget(8000), 20_000)


if __name__ == "__main__":
    unittest.main()
