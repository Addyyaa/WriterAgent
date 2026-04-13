from __future__ import annotations

from pathlib import Path
import sys
import unittest

# 兼容直接执行：python tests/unit/test_hybrid_context_compressor.py
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from packages.llm.text_generation.base import TextGenerationProvider, TextGenerationRequest, TextGenerationResult
from packages.memory.working_memory.hybrid_compressor import HybridContextCompressor


class _FakeProvider(TextGenerationProvider):
    def __init__(self, payload: dict):
        self.payload = payload
        self.last_request: TextGenerationRequest | None = None

    def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        self.last_request = request
        content = str(self.payload.get("compressed") or self.payload.get("content") or "")
        return TextGenerationResult(
            text=content,
            json_data=dict(self.payload),
            model="mock",
            provider="mock",
            is_mock=True,
            raw_response_json={},
        )


class TestHybridContextCompressor(unittest.TestCase):
    def test_local_compress_when_short(self) -> None:
        compressor = HybridContextCompressor(enable_llm=True, text_provider=_FakeProvider({"compressed": "x"}))
        result = compressor.compress(
            text="短文本",
            token_budget=64,
            query="短文本",
            summary_hint=None,
            allow_llm=True,
        )
        self.assertEqual(result.method, "none")
        self.assertFalse(result.llm_attempted)

    def test_llm_used_when_local_truncate(self) -> None:
        text = (
            "北港钟楼线索确认第七条禁令与深渊引擎相关，并在港务日志中记录冲突细节和后续处置。"
            "当晚主角与港务官交涉失败，转而调查旧档案确认禁令条款。"
        )
        compressor = HybridContextCompressor(
            enable_llm=True,
            llm_trigger_ratio=1.0,
            llm_min_gain_ratio=0.5,
            text_provider=_FakeProvider({"compressed": "北港钟楼线索确认第七条禁令与深渊引擎相关，主角与港务官核对旧档案"}),
        )
        result = compressor.compress(
            text=text,
            token_budget=24,
            query="深渊引擎禁令",
            summary_hint=None,
            allow_llm=True,
        )
        self.assertTrue(result.llm_attempted)
        self.assertTrue(result.llm_used)
        self.assertEqual(result.method, "llm_abstractive")

    def test_llm_invalid_numbers_fallback_local(self) -> None:
        text = ("第七条禁令与北港钟楼案件关联并且应当立即冻结深渊引擎计划" * 80).strip()
        compressor = HybridContextCompressor(
            enable_llm=True,
            text_provider=_FakeProvider({"compressed": "第999条禁令"}),
        )
        result = compressor.compress(
            text=text,
            token_budget=20,
            query="第七条",
            summary_hint=None,
            allow_llm=True,
        )
        self.assertTrue(result.llm_attempted)
        self.assertFalse(result.llm_used)
        self.assertNotEqual(result.method, "llm_abstractive")

    def test_llm_drop_many_numbers_fallback_local(self) -> None:
        text = "利润为 1,500,000 美元，成本为 1,200,000 美元，毛利为 300,000 美元，增长率 18%。"
        compressor = HybridContextCompressor(
            enable_llm=True,
            llm_trigger_ratio=1.0,
            text_provider=_FakeProvider({"compressed": "利润很高，增长不错。"}),
        )
        result = compressor.compress(
            text=text * 10,
            token_budget=22,
            query="利润与增长率",
            summary_hint=None,
            allow_llm=True,
        )
        self.assertTrue(result.llm_attempted)
        self.assertFalse(result.llm_used)
        self.assertNotEqual(result.method, "llm_abstractive")

    def test_llm_drop_entities_fallback_local(self) -> None:
        text = ("张三北港钟楼议会秘书李四会面深渊引擎修订案周五提交" * 120).strip()
        compressor = HybridContextCompressor(
            enable_llm=True,
            llm_trigger_ratio=1.0,
            llm_min_gain_ratio=0.9,
            text_provider=_FakeProvider({"compressed": "主角会面并确认计划提交。"}),
        )
        result = compressor.compress(
            text=text,
            token_budget=8,
            query="北港钟楼会面",
            summary_hint=None,
            allow_llm=True,
        )
        self.assertTrue(result.llm_attempted)
        self.assertFalse(result.llm_used)
        self.assertNotEqual(result.method, "llm_abstractive")

    def test_prepare_llm_input_not_naive_head_cut(self) -> None:
        provider = _FakeProvider({"compressed": "保留终局线索X9"})
        compressor = HybridContextCompressor(
            enable_llm=True,
            llm_trigger_ratio=1.0,
            llm_min_gain_ratio=0.9,
            llm_max_input_chars=120,
            text_provider=provider,
        )
        text = (
            "前置信息无关前置信息无关前置信息无关"
            "真正关键终局线索X9在旧档案末尾出现"
        ) * 40
        _ = compressor.compress(
            text=text,
            token_budget=8,
            query="终局线索X9",
            summary_hint=None,
            allow_llm=True,
        )
        self.assertIsNotNone(provider.last_request)
        prompt = str(provider.last_request.user_prompt if provider.last_request else "")
        self.assertIn("终局线索X9", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
