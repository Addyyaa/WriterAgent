from __future__ import annotations

import unittest

from packages.llm.text_generation.base import TextGenerationRequest
from packages.llm.text_generation.openai_compatible import OpenAICompatibleTextProvider
from packages.tools.system_tools.local_data_tools_dispatch import LOCAL_DATA_TOOLS_OPENAI


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

    def test_full_mode_merges_local_tools_tool_choice_auto(self) -> None:
        """挂载本地查询 tools 时不可再强制仅 output function，须 tool_choice=auto。"""

        def _noop_exec(_name: str, _arguments: dict) -> dict:
            return {}

        provider = OpenAICompatibleTextProvider(
            api_key="k",
            model="gpt-4o-mini",
            base_url="https://api.openai.com/v1",
            compat_mode="full",
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
                extra_function_tools=tuple(LOCAL_DATA_TOOLS_OPENAI[:1]),
                local_data_tool_executor=_noop_exec,
            )
        )
        self.assertGreaterEqual(len(payload["tools"]), 2)
        self.assertEqual(payload["tool_choice"], "auto")


if __name__ == "__main__":
    unittest.main()
