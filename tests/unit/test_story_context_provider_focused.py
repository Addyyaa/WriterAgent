"""SQLAlchemyStoryContextProvider.load_focused 条数上界与分支覆盖（无真实 DB）。"""

from __future__ import annotations

import unittest

from packages.workflows.chapter_generation.context_provider import (
    SQLAlchemyStoryContextProvider,
    _is_foreshadow_open,
)


class TestStoryContextProviderFocused(unittest.TestCase):
    def test_load_focused_fallback_character_cap(self) -> None:
        """relevance 未命中角色名时退回宽池子集，角色数不超过 18。"""
        p = SQLAlchemyStoryContextProvider.__new__(SQLAlchemyStoryContextProvider)
        many_chars = [{"name": f"角色{i}", "id": str(i)} for i in range(80)]
        p._list_chapters = lambda **kw: [{"chapter_no": 1, "id": "c1"}]  # type: ignore[method-assign]
        p._list_characters = lambda **kw: many_chars  # type: ignore[method-assign]
        p._list_world_entries = lambda **kw: [{"title": f"词条{i}", "id": str(i)} for i in range(20)]  # type: ignore[method-assign]
        p._list_timeline_events = lambda **kw: []  # type: ignore[method-assign]
        p._list_foreshadowings = lambda **kw: []  # type: ignore[method-assign]
        ctx = p.load_focused(project_id="p1", chapter_no=3, relevance_blob="无关文本")
        self.assertLessEqual(len(ctx.characters), 18)

    def test_load_focused_named_characters_cap(self) -> None:
        """命中至少 3 个角色名时仅保留命中列，且不超过 24。"""
        p = SQLAlchemyStoryContextProvider.__new__(SQLAlchemyStoryContextProvider)
        many_chars = [{"name": f"角色{i}", "id": str(i)} for i in range(80)]
        p._list_chapters = lambda **kw: []  # type: ignore[method-assign]
        p._list_characters = lambda **kw: many_chars  # type: ignore[method-assign]
        p._list_world_entries = lambda **kw: []  # type: ignore[method-assign]
        p._list_timeline_events = lambda **kw: []  # type: ignore[method-assign]
        p._list_foreshadowings = lambda **kw: []  # type: ignore[method-assign]
        blob = "".join(f"角色{i}" for i in range(30))
        ctx = p.load_focused(project_id="p1", chapter_no=1, relevance_blob=blob)
        self.assertLessEqual(len(ctx.characters), 24)
        self.assertGreaterEqual(len(ctx.characters), 3)

    def test_load_focused_open_foreshadowing_cap(self) -> None:
        """开放伏笔在 setup 不晚于当前章前提下最多 8 条。"""
        p = SQLAlchemyStoryContextProvider.__new__(SQLAlchemyStoryContextProvider)
        fores = [
            {
                "id": str(i),
                "setup_chapter_no": 1,
                "status": "open",
                "setup_text": "",
                "expected_payoff": "",
                "payoff_chapter_no": None,
                "payoff_text": "",
            }
            for i in range(20)
        ]
        p._list_chapters = lambda **kw: []  # type: ignore[method-assign]
        p._list_characters = lambda **kw: []  # type: ignore[method-assign]
        p._list_world_entries = lambda **kw: []  # type: ignore[method-assign]
        p._list_timeline_events = lambda **kw: []  # type: ignore[method-assign]
        p._list_foreshadowings = lambda **kw: fores  # type: ignore[method-assign]
        ctx = p.load_focused(project_id="p1", chapter_no=5, relevance_blob="")
        self.assertLessEqual(len(ctx.foreshadowings), 8)

    def test_is_foreshadow_open(self) -> None:
        self.assertTrue(_is_foreshadow_open("open"))
        self.assertTrue(_is_foreshadow_open("PENDING"))
        self.assertFalse(_is_foreshadow_open("resolved"))


if __name__ == "__main__":
    unittest.main()
