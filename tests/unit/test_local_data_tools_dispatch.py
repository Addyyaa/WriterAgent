from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from packages.tools.system_tools.local_data_tools_dispatch import (
    LOCAL_DATA_TOOL_NAMES,
    LOCAL_DATA_TOOLS_OPENAI,
    execute_local_data_tool,
    parse_tool_arguments,
)


class TestLocalDataToolsDispatch(unittest.TestCase):
    def test_openai_tools_count_and_names(self) -> None:
        names = [item["function"]["name"] for item in LOCAL_DATA_TOOLS_OPENAI]
        self.assertEqual(
            names,
            [
                "list_project_chapters",
                "get_character_inventory",
                "search_project_memory_vectors",
                "get_chapter_content",
            ],
        )
        self.assertEqual(LOCAL_DATA_TOOL_NAMES, frozenset(names))

    def test_parse_tool_arguments_empty(self) -> None:
        self.assertEqual(parse_tool_arguments(None), {})
        self.assertEqual(parse_tool_arguments(""), {})

    def test_execute_unknown_tool(self) -> None:
        db = MagicMock()
        pms = MagicMock()
        out = execute_local_data_tool(name="nope", arguments={}, db=db, project_memory_service=pms)
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
