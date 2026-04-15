from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from packages.llm.text_generation.base import TextGenerationRequest
from packages.llm.text_generation.mock_provider import MockTextGenerationProvider
from packages.llm.text_generation.openai_compatible import OpenAICompatibleTextProvider


class TestTextGenerationProviders(unittest.TestCase):
    class _DummyResponse:
        def __init__(self, status_code: int, body: dict):
            self.status_code = status_code
            self._body = body

        def json(self) -> dict:
            return self._body

    def test_mock_provider_is_deterministic(self) -> None:
        provider = MockTextGenerationProvider()
        req = TextGenerationRequest(
            system_prompt="s",
            user_prompt="主角在雨夜追查钟楼守夜人",
            temperature=0.7,
            metadata_json={"target_words": 900},
        )
        r1 = provider.generate(req)
        r2 = provider.generate(req)
        self.assertEqual(r1.json_data, r2.json_data)
        self.assertTrue(r1.is_mock)
        self.assertIn("title", r1.json_data)
        self.assertIn("content", r1.json_data)
        self.assertIn("summary", r1.json_data)

    def test_openai_payload_build(self) -> None:
        provider = OpenAICompatibleTextProvider(
            api_key="k",
            model="m",
            base_url="http://example.com/v1",
        )
        payload = provider.build_chat_payload(
            TextGenerationRequest(
                system_prompt="sys",
                user_prompt="user",
                temperature=0.5,
                max_tokens=512,
            )
        )
        self.assertEqual(payload["model"], "m")
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(payload["messages"][1]["role"], "user")
        self.assertEqual(payload["temperature"], 0.5)
        self.assertEqual(payload["max_tokens"], 512)
        self.assertEqual(payload["response_format"]["type"], "json_object")

    def test_openai_parse_chat_response(self) -> None:
        provider = OpenAICompatibleTextProvider(
            api_key="k",
            model="m",
            base_url="http://example.com/v1",
        )
        body = {
            "model": "demo-model",
            "choices": [
                {
                    "message": {
                        "content": '{"title":"T","content":"C","summary":"S"}'
                    }
                }
            ],
        }
        parsed = provider.parse_chat_response(body)
        self.assertEqual(parsed.model, "demo-model")
        self.assertFalse(parsed.is_mock)
        self.assertEqual(parsed.json_data["title"], "T")
        self.assertEqual(parsed.text, "C")

    def test_openai_parse_chat_response_notes_fallback(self) -> None:
        provider = OpenAICompatibleTextProvider(
            api_key="k",
            model="m",
            base_url="http://example.com/v1",
        )
        body = {
            "model": "demo-model",
            "choices": [
                {
                    "message": {
                        "content": '{"notes":"仅有 notes 字段"}'
                    }
                }
            ],
        }
        parsed = provider.parse_chat_response(body)
        self.assertEqual(parsed.text, "仅有 notes 字段")

    def test_openai_parse_prefers_richer_payload_when_tool_calls_and_content_diverge(self) -> None:
        """模拟厂商同时返回截断的 function.arguments 与完整的 message.content。"""
        provider = OpenAICompatibleTextProvider(
            api_key="k",
            model="m",
            base_url="http://example.com/v1",
        )
        long_chapter = "正文" * 800
        long_payload = {
            "mode": "draft",
            "status": "success",
            "segments": [],
            "word_count": 1600,
            "chapter": {
                "title": "胶带与霜",
                "content": long_chapter,
                "summary": "摘要",
            },
        }
        short_payload = {
            "mode": "draft",
            "status": "success",
            "segments": [],
            "word_count": 2,
            "chapter": {
                "title": "胶带与霜",
                "content": "短",
                "summary": "摘要",
            },
        }
        body = {
            "model": "demo-model",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(long_payload, ensure_ascii=False),
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "chapter_generation_output",
                                    "arguments": json.dumps(short_payload, ensure_ascii=False),
                                },
                            }
                        ],
                    }
                }
            ],
        }
        parsed = provider.parse_chat_response(body)
        self.assertEqual(parsed.json_data["chapter"]["content"], long_chapter)
        self.assertGreater(len(parsed.json_data["chapter"]["content"]), 1000)

    def test_openai_payload_build_with_json_schema(self) -> None:
        provider = OpenAICompatibleTextProvider(
            api_key="k",
            model="m",
            base_url="http://example.com/v1",
        )
        payload = provider.build_chat_payload(
            TextGenerationRequest(
                system_prompt="sys",
                user_prompt="user",
                temperature=0.4,
                response_schema={
                    "type": "object",
                    "required": ["content"],
                    "properties": {"content": {"type": "string"}},
                },
                response_schema_name="chapter_schema",
                response_schema_strict=True,
            )
        )
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertEqual(payload["response_format"]["json_schema"]["name"], "chapter_schema")
        self.assertTrue(payload["response_format"]["json_schema"]["strict"])

    def test_openai_payload_build_with_function_calling(self) -> None:
        provider = OpenAICompatibleTextProvider(
            api_key="k",
            model="m",
            base_url="http://example.com/v1",
        )
        payload = provider.build_chat_payload(
            TextGenerationRequest(
                system_prompt="sys",
                user_prompt="user",
                temperature=0.4,
                response_schema={
                    "type": "object",
                    "required": ["content"],
                    "properties": {"content": {"type": "string"}},
                },
                response_schema_name="chapter_schema",
                use_function_calling=True,
                function_name="chapter_output",
                function_description="Return chapter json",
            )
        )
        self.assertEqual(payload["tools"][0]["type"], "function")
        self.assertEqual(payload["tools"][0]["function"]["name"], "chapter_output")
        self.assertEqual(payload["tool_choice"]["function"]["name"], "chapter_output")
        self.assertNotIn("response_format", payload)

    def test_openai_parse_chat_response_invalid_json(self) -> None:
        provider = OpenAICompatibleTextProvider(
            api_key="k",
            model="m",
            base_url="http://example.com/v1",
        )
        with self.assertRaises(RuntimeError):
            provider.parse_chat_response(
                {
                    "choices": [
                        {"message": {"content": "not-json"}}
                    ]
                }
            )

    def test_openai_raise_api_error(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            OpenAICompatibleTextProvider.raise_api_error(
                status_code=429,
                body={"error": {"message": "rate limit"}},
            )
        self.assertIn("429", str(ctx.exception))
        self.assertIn("rate limit", str(ctx.exception))

    def test_openai_generate_real_request_success(self) -> None:
        provider = OpenAICompatibleTextProvider(
            api_key="k",
            model="m",
            base_url="http://example.com/v1",
        )
        req = TextGenerationRequest(
            system_prompt="sys",
            user_prompt="user",
            temperature=0.3,
        )
        body = {
            "model": "m",
            "choices": [
                {"message": {"content": '{"title":"T","content":"C","summary":"S"}'}}
            ],
        }
        with patch(
            "packages.llm.text_generation.openai_compatible.httpx.post",
            return_value=self._DummyResponse(status_code=200, body=body),
        ):
            result = provider.generate(req)
        self.assertFalse(result.is_mock)
        self.assertEqual(result.text, "C")
        self.assertEqual(result.json_data["title"], "T")

    def test_openai_generate_raises_on_transport_error(self) -> None:
        """网络/传输失败时不再回退 mock，应向调用方抛出异常。"""
        provider = OpenAICompatibleTextProvider(
            api_key="k",
            model="m",
            base_url="http://example.com/v1",
        )
        req = TextGenerationRequest(
            system_prompt="sys",
            user_prompt="测试不回退",
            temperature=0.3,
        )
        with patch(
            "packages.llm.text_generation.openai_compatible.httpx.post",
            side_effect=RuntimeError("network down"),
        ):
            with self.assertRaises(RuntimeError):
                provider.generate(req)

    def test_prompt_guard_compresses_oversized_prompt_before_request(self) -> None:
        provider = OpenAICompatibleTextProvider(
            api_key="k",
            model="m",
            base_url="http://example.com/v1",
            prompt_guard_enabled=True,
            model_context_window_tokens=220,
            prompt_guard_output_reserve_tokens=80,
            prompt_guard_overhead_tokens=20,
            prompt_guard_max_attempts=1,
        )
        req = TextGenerationRequest(
            system_prompt="sys",
            user_prompt=("超长上下文 " * 1400).strip(),
            temperature=0.3,
            max_tokens=80,
            metadata_json={"writing_goal": "测试压缩"},
        )
        body = {
            "model": "m",
            "choices": [
                {"message": {"content": '{"title":"T","content":"C","summary":"S"}'}}
            ],
        }
        captured_payload: dict = {}

        def _post(*_args, **kwargs):
            captured_payload.update(kwargs.get("json") or {})
            return self._DummyResponse(status_code=200, body=body)

        with patch.object(
            provider,
            "_compress_user_prompt_by_llm",
            return_value=("压缩后提示词", "llm_abstractive", True),
        ):
            with patch(
                "packages.llm.text_generation.openai_compatible.httpx.post",
                side_effect=_post,
            ):
                result = provider.generate(req)
        self.assertFalse(result.is_mock)
        self.assertEqual(
            captured_payload["messages"][1]["content"],
            "压缩后提示词",
        )
        self.assertTrue(result.raw_response_json["prompt_guard"]["applied"])

    def test_prompt_guard_retries_once_on_context_length_error(self) -> None:
        provider = OpenAICompatibleTextProvider(
            api_key="k",
            model="m",
            base_url="http://example.com/v1",
            prompt_guard_enabled=True,
            model_context_window_tokens=64000,
            prompt_guard_output_reserve_tokens=1024,
            prompt_guard_overhead_tokens=128,
            prompt_guard_max_attempts=1,
        )
        req = TextGenerationRequest(
            system_prompt="sys",
            user_prompt="原始提示词",
            temperature=0.3,
            max_tokens=256,
            metadata_json={"writing_goal": "测试二次重试"},
        )
        success_body = {
            "model": "m",
            "choices": [
                {"message": {"content": '{"title":"T","content":"C","summary":"S"}'}}
            ],
        }
        responses = [
            self._DummyResponse(
                status_code=400,
                body={"error": {"message": "maximum context length is 8192 tokens"}},
            ),
            self._DummyResponse(status_code=200, body=success_body),
        ]
        sent_user_prompts: list[str] = []

        def _post(*_args, **kwargs):
            payload = kwargs.get("json") or {}
            sent_user_prompts.append(str(payload["messages"][1]["content"]))
            return responses.pop(0)

        with patch.object(
            provider,
            "_compress_user_prompt_by_llm",
            return_value=("二次压缩后的提示词", "llm_abstractive", True),
        ) as compress_mock:
            with patch(
                "packages.llm.text_generation.openai_compatible.httpx.post",
                side_effect=_post,
            ):
                result = provider.generate(req)
        self.assertFalse(result.is_mock)
        self.assertGreaterEqual(compress_mock.call_count, 1)
        self.assertEqual(len(sent_user_prompts), 2)
        self.assertEqual(sent_user_prompts[0], "原始提示词")
        self.assertEqual(sent_user_prompts[1], "二次压缩后的提示词")
        self.assertTrue(result.raw_response_json["prompt_guard"]["second_retry_applied"])

    def test_schema_validate_repair_retry_success(self) -> None:
        provider = OpenAICompatibleTextProvider(
            api_key="k",
            model="m",
            base_url="http://example.com/v1",
            prompt_guard_enabled=False,
        )
        req = TextGenerationRequest(
            system_prompt="sys",
            user_prompt="请输出章节",
            temperature=0.3,
            response_schema={
                "type": "object",
                "required": ["title", "content"],
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                    "content": {"type": "string", "minLength": 1},
                },
                "additionalProperties": True,
            },
            validation_retries=1,
        )
        responses = [
            self._DummyResponse(
                status_code=200,
                body={"model": "m", "choices": [{"message": {"content": '{"title":"只有标题"}'}}]},
            ),
            self._DummyResponse(
                status_code=200,
                body={
                    "model": "m",
                    "choices": [{"message": {"content": '{"title":"T","content":"C"}'}}],
                },
            ),
        ]
        with patch(
            "packages.llm.text_generation.openai_compatible.httpx.post",
            side_effect=lambda *_args, **_kwargs: responses.pop(0),
        ):
            result = provider.generate(req)
        self.assertFalse(result.is_mock)
        self.assertEqual(result.json_data["content"], "C")
        self.assertEqual(result.raw_response_json["prompt_guard"]["schema_repair_attempts"], 1)

    def test_parse_tool_call_arguments(self) -> None:
        provider = OpenAICompatibleTextProvider(
            api_key="k",
            model="m",
            base_url="http://example.com/v1",
        )
        body = {
            "model": "demo-model",
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "chapter_output",
                                    "arguments": '{"title":"T","content":"C","summary":"S"}',
                                },
                            }
                        ]
                    }
                }
            ],
        }
        parsed = provider.parse_chat_response(body)
        self.assertEqual(parsed.json_data["title"], "T")
        self.assertEqual(parsed.text, "C")

    def test_input_schema_validation_strict_fail(self) -> None:
        provider = OpenAICompatibleTextProvider(
            api_key="k",
            model="m",
            base_url="http://example.com/v1",
        )
        req = TextGenerationRequest(
            system_prompt="sys",
            user_prompt='{"goal": 123}',
            input_schema={
                "type": "object",
                "required": ["goal"],
                "properties": {"goal": {"type": "string", "minLength": 1}},
                "additionalProperties": True,
            },
            input_schema_name="chapter_input",
            input_schema_strict=True,
        )
        with self.assertRaises(RuntimeError) as ctx:
            provider.generate(req)
        self.assertIn("chapter_input", str(ctx.exception))

    def test_input_schema_validation_non_strict_warning(self) -> None:
        provider = OpenAICompatibleTextProvider(
            api_key="k",
            model="m",
            base_url="http://example.com/v1",
        )
        req = TextGenerationRequest(
            system_prompt="sys",
            user_prompt='{"goal": 123}',
            input_schema={
                "type": "object",
                "required": ["goal"],
                "properties": {"goal": {"type": "string", "minLength": 1}},
                "additionalProperties": True,
            },
            input_schema_name="chapter_input",
            input_schema_strict=False,
        )
        body = {
            "model": "m",
            "choices": [
                {"message": {"content": '{"title":"T","content":"C","summary":"S"}'}}
            ],
        }
        with patch(
            "packages.llm.text_generation.openai_compatible.httpx.post",
            return_value=self._DummyResponse(status_code=200, body=body),
        ):
            result = provider.generate(req)
        input_validation = dict(result.raw_response_json.get("input_validation") or {})
        self.assertTrue(input_validation.get("applied"))
        self.assertEqual(input_validation.get("schema_name"), "chapter_input")
        self.assertGreater(len(input_validation.get("warnings") or []), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
