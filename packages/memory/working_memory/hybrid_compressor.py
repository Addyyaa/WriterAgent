from __future__ import annotations

import re
from dataclasses import dataclass

from packages.core.utils import (
    compress_text_to_budget,
    estimate_token_count,
    extract_query_terms,
    normalize_whitespace,
)
from packages.llm.text_generation.base import TextGenerationProvider, TextGenerationRequest


_NUM_RE = re.compile(r"\d[\d,\.]*")
_ENTITY_QUOTED_RE = re.compile(r"[《「『](.+?)[》」』]")
_ENTITY_EN_RE = re.compile(r"\b(?:[A-Z]{2,}|[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b")
_ENTITY_CJK_RE = re.compile(r"[\u4e00-\u9fff]{2,8}")
_CJK_ENTITY_SUFFIXES = (
    "市",
    "省",
    "县",
    "镇",
    "港",
    "湾",
    "河",
    "湖",
    "山",
    "城",
    "馆",
    "院",
    "会",
    "局",
    "司",
    "队",
    "组",
    "站",
)


@dataclass(frozen=True)
class CompressionResult:
    text: str
    method: str
    original_tokens: int
    compressed_tokens: int
    llm_attempted: bool = False
    llm_used: bool = False


class HybridContextCompressor:
    """混合上下文压缩器：本地优先，必要时走 LLM，失败自动回退。"""

    def __init__(
        self,
        *,
        text_provider: TextGenerationProvider | None = None,
        enable_llm: bool = False,
        llm_trigger_ratio: float = 1.6,
        llm_min_gain_ratio: float = 0.12,
        llm_max_input_chars: int = 6000,
        numeric_min_keep_ratio: float = 0.5,
        numeric_min_check_count: int = 3,
        entity_min_keep_ratio: float = 0.8,
        entity_min_check_count: int = 3,
    ) -> None:
        self.text_provider = text_provider
        self.enable_llm = bool(enable_llm)
        self.llm_trigger_ratio = max(1.0, float(llm_trigger_ratio))
        self.llm_min_gain_ratio = max(0.0, min(float(llm_min_gain_ratio), 0.9))
        self.llm_max_input_chars = max(200, int(llm_max_input_chars))
        self.numeric_min_keep_ratio = max(0.0, min(1.0, float(numeric_min_keep_ratio)))
        self.numeric_min_check_count = max(1, int(numeric_min_check_count))
        self.entity_min_keep_ratio = max(0.0, min(1.0, float(entity_min_keep_ratio)))
        self.entity_min_check_count = max(1, int(entity_min_check_count))

    def compress(
        self,
        *,
        text: str,
        token_budget: int,
        query: str,
        summary_hint: str | None = None,
        allow_llm: bool = True,
    ) -> CompressionResult:
        normalized = normalize_whitespace(text or "")
        if token_budget <= 0 or not normalized:
            return CompressionResult(
                text="",
                method="empty",
                original_tokens=0,
                compressed_tokens=0,
                llm_attempted=False,
                llm_used=False,
            )

        original_tokens = estimate_token_count(normalized)

        local_text, local_method = compress_text_to_budget(
            normalized,
            token_budget=token_budget,
            query=query,
            fallback_summary=summary_hint,
        )
        local_tokens = estimate_token_count(local_text)

        if not self._should_try_llm(
            allow_llm=allow_llm,
            original_tokens=original_tokens,
            local_tokens=local_tokens,
            local_method=local_method,
            token_budget=token_budget,
        ):
            return CompressionResult(
                text=local_text,
                method=local_method,
                original_tokens=original_tokens,
                compressed_tokens=local_tokens,
                llm_attempted=False,
                llm_used=False,
            )

        llm_text = self._compress_with_llm(
            text=normalized,
            query=query,
            token_budget=token_budget,
        )
        if not llm_text:
            return CompressionResult(
                text=local_text,
                method=local_method,
                original_tokens=original_tokens,
                compressed_tokens=local_tokens,
                llm_attempted=True,
                llm_used=False,
            )

        llm_text = normalize_whitespace(llm_text)
        llm_tokens = estimate_token_count(llm_text)
        if llm_tokens > token_budget:
            llm_text, _ = compress_text_to_budget(
                llm_text,
                token_budget=token_budget,
                query=query,
                fallback_summary=summary_hint,
            )
            llm_tokens = estimate_token_count(llm_text)

        soft_budget_ok = (
            local_method == "truncate"
            and llm_tokens > token_budget
            and llm_tokens < local_tokens
            and llm_tokens <= max(token_budget + 32, int(local_tokens * 0.92))
        )
        if not llm_text or (llm_tokens > token_budget and not soft_budget_ok):
            return CompressionResult(
                text=local_text,
                method=local_method,
                original_tokens=original_tokens,
                compressed_tokens=local_tokens,
                llm_attempted=True,
                llm_used=False,
            )

        if not self._validate_faithfulness(
            original=normalized,
            compressed=llm_text,
            query=query,
            numeric_min_keep_ratio=self.numeric_min_keep_ratio,
            numeric_min_check_count=self.numeric_min_check_count,
            entity_min_keep_ratio=self.entity_min_keep_ratio,
            entity_min_check_count=self.entity_min_check_count,
        ):
            return CompressionResult(
                text=local_text,
                method=local_method,
                original_tokens=original_tokens,
                compressed_tokens=local_tokens,
                llm_attempted=True,
                llm_used=False,
            )

        return CompressionResult(
            text=llm_text,
            method="llm_abstractive",
            original_tokens=original_tokens,
            compressed_tokens=llm_tokens,
            llm_attempted=True,
            llm_used=True,
        )

    def _should_try_llm(
        self,
        *,
        allow_llm: bool,
        original_tokens: int,
        local_tokens: int,
        local_method: str,
        token_budget: int,
    ) -> bool:
        if not allow_llm or not self.enable_llm or self.text_provider is None:
            return False

        if original_tokens <= token_budget:
            return False

        # 本地压缩效果较好且不是硬截断时，不再额外付出 LLM 成本。
        gain = (original_tokens - max(1, local_tokens)) / max(1, original_tokens)
        if local_method in {"summary_hint", "extractive"} and gain >= self.llm_min_gain_ratio:
            return False

        if local_method == "truncate":
            return True

        return original_tokens >= int(token_budget * self.llm_trigger_ratio)

    def _compress_with_llm(self, *, text: str, query: str, token_budget: int) -> str | None:
        if self.text_provider is None:
            return None
        safe_text = self._prepare_llm_input(text=text, query=query)
        system_prompt = (
            "# Role\n"
            "你是一位专门为RAG系统设计的“高密度信息提炼专家”。\n\n"
            "# Task\n"
            "你的目标是对输入文本进行极端压缩，最大化Token利用率。请剔除所有冗余的修饰语、客套话和过渡句，"
            "只保留具有高信息密度的核心事实。\n\n"
            "# Constraints (严格遵循)\n"
            "1. **实体保真**：严禁修改人名、地名、专有名词、时间（精确到分秒）和具体数字。\n"
            "2. **逻辑骨架**：必须完整保留因果、转折（但/然而）、条件（如果/除非）、否定（不/非）等逻辑连接词。\n"
            "3. **去噪**：删除形容词、副词及任何不影响语义理解的废话。\n"
            "4. **输出格式**：仅输出标准JSON字符串，不要包含Markdown标记或其他任何文字。\n\n"
            "# Output Example\n"
            "Input: '尽管昨天天气非常恶劣，下着大雨，但张三还是坚持在下午3点完成了任务，耗时5个小时。'\n"
            "Output: {\"compressed\": \"尽管昨天天气恶劣，张三于下午3点完成任务，耗时5小时。\"}\n\n"
            "# Input\n"
            "下方 user prompt 的 text 字段即待压缩文本。"
        )
        user_prompt = (
            "请压缩以下文本，严格控制在预算内。\n"
            f"query={query}\n"
            f"token_budget={int(token_budget)}\n"
            f"text={safe_text}"
        )

        try:
            result = self.text_provider.generate(
                TextGenerationRequest(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=0.1,
                    max_tokens=max(64, token_budget * 2),
                    metadata_json={
                        "workflow": "context_compression",
                        "mode": "abstractive",
                    },
                )
            )
        except Exception:
            return None

        candidate = str(result.json_data.get("compressed") or result.json_data.get("content") or "").strip()
        if not candidate:
            return None
        return candidate

    def _prepare_llm_input(self, *, text: str, query: str) -> str:
        normalized = normalize_whitespace(text or "")
        if len(normalized) <= self.llm_max_input_chars:
            return normalized

        # 避免“硬截断仅保留前半段”导致关键信息丢失，先做一轮本地抽取浓缩。
        pre_budget_tokens = max(64, self.llm_max_input_chars // 2)
        compact, _ = compress_text_to_budget(
            normalized,
            token_budget=pre_budget_tokens,
            query=query,
            fallback_summary=None,
        )
        compact = normalize_whitespace(compact)
        if not compact:
            compact = normalized
        if len(compact) > self.llm_max_input_chars:
            compact = compact[: self.llm_max_input_chars].rstrip()
        return compact

    @staticmethod
    def _validate_faithfulness(
        *,
        original: str,
        compressed: str,
        query: str,
        numeric_min_keep_ratio: float,
        numeric_min_check_count: int,
        entity_min_keep_ratio: float,
        entity_min_check_count: int,
    ) -> bool:
        if not compressed:
            return False

        # 1) 数字保真：不允许引入新数字，且在数字较多时不能大量丢失。
        origin_nums = HybridContextCompressor._extract_numbers(original)
        comp_nums = HybridContextCompressor._extract_numbers(compressed)
        if comp_nums - origin_nums:
            return False
        if len(origin_nums) >= numeric_min_check_count:
            keep_ratio = len(origin_nums & comp_nums) / max(1, len(origin_nums))
            if keep_ratio < numeric_min_keep_ratio:
                return False

        # 2) 轻量实体保真：实体数量足够时，需保留大部分实体。
        origin_entities = HybridContextCompressor._extract_entities(original)
        comp_entities = HybridContextCompressor._extract_entities(compressed)
        if len(origin_entities) >= entity_min_check_count:
            keep_ratio = len(origin_entities & comp_entities) / max(1, len(origin_entities))
            if keep_ratio < entity_min_keep_ratio:
                return False

        # 3) Query 词覆盖：若 query 有关键词，至少保留一个关键词。
        q_terms = extract_query_terms(query, max_terms=12)
        if q_terms:
            lowered = compressed.lower()
            if not any(term in lowered for term in q_terms):
                return False

        # 4) 长度合理：避免“过短导致语义空洞”。
        if estimate_token_count(compressed) < 6:
            return False

        return True

    @staticmethod
    def _extract_numbers(text: str) -> set[str]:
        raw = _NUM_RE.findall(text or "")
        out: set[str] = set()
        for item in raw:
            normalized = item.strip().replace(",", "")
            if normalized:
                out.add(normalized)
        return out

    @staticmethod
    def _extract_entities(text: str) -> set[str]:
        normalized = normalize_whitespace(text or "")
        entities: set[str] = set()
        if not normalized:
            return entities

        for match in _ENTITY_QUOTED_RE.findall(normalized):
            token = normalize_whitespace(str(match or ""))
            if len(token) >= 2:
                entities.add(token.lower())

        for match in _ENTITY_EN_RE.findall(normalized):
            token = normalize_whitespace(str(match or ""))
            if len(token) >= 2:
                entities.add(token.lower())

        for match in _ENTITY_CJK_RE.findall(normalized):
            token = str(match or "").strip()
            if len(token) < 2:
                continue
            if token.endswith(_CJK_ENTITY_SUFFIXES) or len(token) <= 3:
                entities.add(token.lower())
        return entities
