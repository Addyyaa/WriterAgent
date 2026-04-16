from __future__ import annotations

import unittest

from packages.llm.text_generation.base import TextGenerationRequest
from packages.llm.text_generation.openai_compatible import OpenAICompatibleTextProvider


class TestOpenAICompatiblePayloadBasicFC(unittest.TestCase):
    def test_basic_mode_prefers_function_calling_when_enabled(self) -> None:
        provider = OpenAICompatibleTextProvider(
            api_key="k",
            model="qwen-plus",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            compat_mode="basic",
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
                use_function_calling=True,
                function_name="chapter_output",
            )
        )
        self.assertIn("tools", payload)
        # DashScope 不接受强制 function tool_choice（会报 InvalidParameter / required）
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertNotIn("response_format", payload)
        self.assertIn("JSON Schema", payload["messages"][1]["content"])

    def test_basic_mode_without_function_calling_uses_json_object(self) -> None:
        provider = OpenAICompatibleTextProvider(
            api_key="k",
            model="qwen-plus",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            compat_mode="basic",
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
                use_function_calling=False,
            )
        )
        self.assertEqual(payload["response_format"]["type"], "json_object")

    def test_max_tokens_clamped_to_provider_cap(self) -> None:
        provider = OpenAICompatibleTextProvider(
            api_key="k",
            model="qwen-plus",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            compat_mode="basic",
            max_output_tokens_cap=8192,
        )
        payload = provider.build_chat_payload(
            TextGenerationRequest(
                system_prompt="sys",
                user_prompt="user",
                temperature=0.4,
                max_tokens=32_000,
                response_schema={"type": "object", "properties": {"x": {"type": "string"}}},
                use_function_calling=False,
            )
        )
        self.assertEqual(payload["max_tokens"], 8192)

    def test_read_timeout_for_request_override(self) -> None:
        provider = OpenAICompatibleTextProvider(
            api_key="k",
            model="qwen-plus",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            compat_mode="basic",
            timeout_seconds=120.0,
        )
        req = TextGenerationRequest(
            system_prompt="s",
            user_prompt="u",
            timeout_seconds=450.0,
        )
        self.assertEqual(provider._read_timeout_for(req), 450.0)
        over = TextGenerationRequest(
            system_prompt="s",
            user_prompt="u",
            timeout_seconds=1000.0,
        )
        self.assertEqual(provider._read_timeout_for(over), 900.0)


if __name__ == "__main__":
    unittest.main()
