from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from packages.llm.text_generation.openai_compatible import OpenAICompatibleTextProvider
from packages.llm.text_generation.schema_errors import ResponseSchemaValidationError
from packages.workflows.consistency_review.evidence_tool_loop import (
    FETCH_CONSISTENCY_EVIDENCE,
    run_consistency_review_tool_loop,
)


class _SeqChatProvider:
    def __init__(self, bodies: list[dict], *, with_schema: bool = False) -> None:
        self._bodies = bodies
        self._i = 0
        self.model = "mock-model"
        self._schema_checker: OpenAICompatibleTextProvider | None = None
        if with_schema:
            self._schema_checker = OpenAICompatibleTextProvider(
                api_key="test-key",
                model="mock-model",
                base_url="https://api.openai.com/v1",
            )

    def _validate_response_schema(self, *, payload: object, schema: dict) -> list[str]:
        if self._schema_checker is None:
            return []
        return self._schema_checker._validate_response_schema(payload=payload, schema=schema)

    def chat_completions(self, **kwargs):  # noqa: ANN003
        if self._i >= len(self._bodies):
            raise RuntimeError("no more bodies")
        b = self._bodies[self._i]
        self._i += 1
        return b


class TestConsistencyEvidenceToolLoop(unittest.TestCase):
    def test_two_round_fetch_then_output(self) -> None:
        out_args = {
            "overall_status": "passed",
            "audit_summary": "ok",
            "issues": [],
        }
        bodies = [
            {
                "model": "m",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": FETCH_CONSISTENCY_EVIDENCE,
                                        "arguments": json.dumps(
                                            {"scope": "character", "entity_id": str("0" * 32)}
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ],
            },
            {
                "model": "m",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "call_2",
                                    "type": "function",
                                    "function": {
                                        "name": "consistency_review_output",
                                        "arguments": json.dumps(out_args, ensure_ascii=False),
                                    },
                                }
                            ],
                        }
                    }
                ],
            },
        ]
        fetch_mock = MagicMock(
            return_value={"found": True, "scope": "character", "entity": {"id": "x"}}
        )
        schema = {
            "type": "object",
            "required": ["overall_status", "audit_summary", "issues"],
            "properties": {
                "overall_status": {"type": "string"},
                "audit_summary": {"type": "string"},
                "issues": {"type": "array"},
            },
        }
        result = run_consistency_review_tool_loop(
            _SeqChatProvider(bodies),
            system_prompt="sys",
            user_json="{}",
            output_schema=schema,
            output_function_name="consistency_review_output",
            output_description="out",
            fetch_handler=fetch_mock,
            max_rounds=4,
        )
        self.assertEqual(result.json_data.get("overall_status"), "passed")
        fetch_mock.assert_called_once()

    def test_schema_reject_then_accept(self) -> None:
        schema = {
            "type": "object",
            "required": ["overall_status", "audit_summary", "issues"],
            "properties": {
                "overall_status": {"type": "string"},
                "audit_summary": {"type": "string"},
                "issues": {"type": "array"},
            },
        }
        bad_args = {"overall_status": "passed", "issues": []}
        good_args = {"overall_status": "passed", "audit_summary": "ok", "issues": []}
        bodies = [
            {
                "model": "m",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {
                                        "name": "consistency_review_output",
                                        "arguments": json.dumps(bad_args, ensure_ascii=False),
                                    },
                                }
                            ],
                        }
                    }
                ],
            },
            {
                "model": "m",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c2",
                                    "type": "function",
                                    "function": {
                                        "name": "consistency_review_output",
                                        "arguments": json.dumps(good_args, ensure_ascii=False),
                                    },
                                }
                            ],
                        }
                    }
                ],
            },
        ]
        fetch_mock = MagicMock(return_value={})
        result = run_consistency_review_tool_loop(
            _SeqChatProvider(bodies, with_schema=True),
            system_prompt="sys",
            user_json="{}",
            output_schema=schema,
            output_function_name="consistency_review_output",
            output_description="out",
            fetch_handler=fetch_mock,
            max_rounds=4,
            validation_retries=1,
        )
        self.assertEqual(result.json_data.get("audit_summary"), "ok")
        fetch_mock.assert_not_called()

    def test_max_fetches_blocks_extra_calls(self) -> None:
        def _tc(tid: str, eid: str) -> dict:
            return {
                "id": tid,
                "type": "function",
                "function": {
                    "name": FETCH_CONSISTENCY_EVIDENCE,
                    "arguments": json.dumps({"scope": "character", "entity_id": eid}),
                },
            }

        out_args = {
            "overall_status": "passed",
            "audit_summary": "ok",
            "issues": [],
        }
        bodies = [
            {
                "model": "m",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                _tc("a", "00000000-0000-4000-8000-000000000001"),
                                _tc("b", "00000000-0000-4000-8000-000000000002"),
                                _tc("c", "00000000-0000-4000-8000-000000000003"),
                            ],
                        }
                    }
                ],
            },
            {
                "model": "m",
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "d",
                                    "type": "function",
                                    "function": {
                                        "name": "consistency_review_output",
                                        "arguments": json.dumps(out_args, ensure_ascii=False),
                                    },
                                }
                            ],
                        }
                    }
                ],
            },
        ]
        fetch_mock = MagicMock(
            side_effect=[
                {"found": True, "n": 1},
                {"found": True, "n": 2},
            ]
        )
        schema = {
            "type": "object",
            "required": ["overall_status", "audit_summary", "issues"],
            "properties": {
                "overall_status": {"type": "string"},
                "audit_summary": {"type": "string"},
                "issues": {"type": "array"},
            },
        }
        run_consistency_review_tool_loop(
            _SeqChatProvider(bodies),
            system_prompt="sys",
            user_json="{}",
            output_schema=schema,
            output_function_name="consistency_review_output",
            output_description="out",
            fetch_handler=fetch_mock,
            max_fetches=2,
            max_rounds=4,
        )
        self.assertEqual(fetch_mock.call_count, 2)

    def test_fetch_denied_when_not_in_allowlist(self) -> None:
        out_args = {
            "overall_status": "passed",
            "audit_summary": "ok",
            "issues": [],
        }
        bad_id = "00000000-0000-4000-8000-000000000099"
        allowed = "00000000-0000-4000-8000-000000000001"
        bodies = [
            {
                "model": "m",
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {
                                        "name": FETCH_CONSISTENCY_EVIDENCE,
                                        "arguments": json.dumps(
                                            {"scope": "character", "entity_id": bad_id}
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ],
            },
            {
                "model": "m",
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "c2",
                                    "type": "function",
                                    "function": {
                                        "name": "consistency_review_output",
                                        "arguments": json.dumps(out_args, ensure_ascii=False),
                                    },
                                }
                            ],
                        }
                    }
                ],
            },
        ]
        fetch_mock = MagicMock(return_value={"found": True})
        schema = {
            "type": "object",
            "required": ["overall_status", "audit_summary", "issues"],
            "properties": {
                "overall_status": {"type": "string"},
                "audit_summary": {"type": "string"},
                "issues": {"type": "array"},
            },
        }
        run_consistency_review_tool_loop(
            _SeqChatProvider(bodies),
            system_prompt="sys",
            user_json="{}",
            output_schema=schema,
            output_function_name="consistency_review_output",
            output_description="out",
            fetch_handler=fetch_mock,
            max_rounds=4,
            entity_id_allowlist={allowed},
        )
        fetch_mock.assert_not_called()

    def test_schema_fail_exceeding_retries_raises(self) -> None:
        schema = {
            "type": "object",
            "required": ["overall_status", "audit_summary", "issues"],
            "properties": {
                "overall_status": {"type": "string"},
                "audit_summary": {"type": "string"},
                "issues": {"type": "array"},
            },
        }
        bad_args = {"overall_status": "passed", "issues": []}
        bodies = [
            {
                "model": "m",
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {
                                        "name": "consistency_review_output",
                                        "arguments": json.dumps(bad_args, ensure_ascii=False),
                                    },
                                }
                            ],
                        }
                    }
                ],
            },
            {
                "model": "m",
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "c2",
                                    "type": "function",
                                    "function": {
                                        "name": "consistency_review_output",
                                        "arguments": json.dumps(bad_args, ensure_ascii=False),
                                    },
                                }
                            ],
                        }
                    }
                ],
            },
        ]
        with self.assertRaises(ResponseSchemaValidationError):
            run_consistency_review_tool_loop(
                _SeqChatProvider(bodies, with_schema=True),
                system_prompt="sys",
                user_json="{}",
                output_schema=schema,
                output_function_name="consistency_review_output",
                output_description="out",
                fetch_handler=MagicMock(),
                max_rounds=4,
                validation_retries=1,
            )


if __name__ == "__main__":
    unittest.main()
