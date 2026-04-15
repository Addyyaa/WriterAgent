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


if __name__ == "__main__":
    unittest.main()
