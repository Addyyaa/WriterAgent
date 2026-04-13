from __future__ import annotations

import hashlib


def stable_bucket_ratio(key: str) -> float:
    """将字符串稳定映射到 [0, 1]，用于 A/B 分桶。"""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF
