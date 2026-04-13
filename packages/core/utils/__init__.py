"""跨业务通用工具函数。"""

from packages.core.utils.hashing import stable_bucket_ratio
from packages.core.utils.simple_yaml import parse_simple_yaml
from packages.core.utils.text import (
    compress_text_to_budget,
    dedupe_keep_order,
    ensure_non_empty_string,
    estimate_token_count,
    extract_query_terms,
    normalize_whitespace,
    split_sentences,
    summarize_text_extractive,
)
from packages.core.utils.time import utc_now_iso

__all__ = [
    "compress_text_to_budget",
    "dedupe_keep_order",
    "ensure_non_empty_string",
    "estimate_token_count",
    "extract_query_terms",
    "normalize_whitespace",
    "parse_simple_yaml",
    "split_sentences",
    "stable_bucket_ratio",
    "summarize_text_extractive",
    "utc_now_iso",
]
