"""章节写作相关的字数与 token 预算估算（中文小说场景）。"""

from __future__ import annotations

import os


def count_fiction_word_units(text: str) -> int:
    """
    统计正文「有效字数」：非空白字符数。

    用于与 target_words 对齐校验（中文网文常用口径：标点与汉字均计入，不含换行与空格）。
    """
    if not text:
        return 0
    return sum(1 for ch in text if not ch.isspace())


def chapter_max_output_tokens(
    target_words: int,
    *,
    cap: int | None = None,
) -> int:
    """
    根据目标字数估算章节 JSON 输出所需的 max_tokens 上限。

    经验：中文正文约 0.9~1.4 token/字（模型与分词器不同），此处取偏保守系数并加标题/摘要/JSON 结构余量。
    """
    tw = max(300, min(10_000, int(target_words)))
    raw_cap = int(os.environ.get("WRITER_CHAPTER_MAX_OUTPUT_TOKENS_CAP", "32000"))
    limit = int(cap) if cap is not None else raw_cap
    limit = max(2048, min(limit, 128_000))
    # 系数 1.45：覆盖偏「密」的正文；+3200 容纳 title/summary/JSON 包装与分段结构
    estimated = int(tw * 1.45) + 3200
    return min(limit, max(4096, estimated))


def chapter_context_token_budget(target_words: int, *, explicit: int | None = None) -> int:
    """
    根据目标字数建议工作记忆检索的 token 预算；若调用方已显式传入则直接返回（仍做上下界裁剪）。
    """
    if explicit is not None:
        return max(400, min(24_000, int(explicit)))
    tw = max(300, min(10_000, int(target_words)))
    # 长章节需要更大检索预算：与目标字数近似线性，上限 20000 与 API 校验一致
    blended = int(tw * 1.85 + 3600)
    return max(3200, min(20_000, blended))


def chapter_word_count_allowed_range(target_words: int) -> tuple[int, int]:
    """目标字数 ±10% 的闭区间。"""
    tw = max(300, min(10_000, int(target_words)))
    low = int(tw * 0.9)
    high = int(tw * 1.1)
    return low, high


def chapter_word_count_violation_message(
    *,
    effective_chars: int,
    target_words: int,
    low: int,
    high: int,
) -> str:
    """
    字数未落在 [low, high] 时的用户可读说明（区分偏短与偏长，避免笼统说「超出区间」）。
    """
    wc = int(effective_chars)
    tw = int(target_words)
    lo = int(low)
    hi = int(high)
    if wc < lo:
        return (
            f"章节正文有效字数为 {wc}（非空白字符数），低于目标 {tw} 所允许的最小值 {lo}；"
            f"允许区间为 [{lo}, {hi}]（target_words 的 ±10%）。"
        )
    return (
        f"章节正文有效字数为 {wc}（非空白字符数），高于目标 {tw} 所允许的最大值 {hi}；"
        f"允许区间为 [{lo}, {hi}]（target_words 的 ±10%）。"
    )
