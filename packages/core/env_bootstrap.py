"""仓库根目录 `.env` 加载（无 python-dotenv 依赖，供 API / Worker / 脚本共用）。"""

from __future__ import annotations

import logging
import os
from pathlib import Path

_logger = logging.getLogger("writeragent.bootstrap")

_LOADED = False


def repo_root() -> Path:
    """`packages/core/env_bootstrap.py` → 仓库根。"""
    return Path(__file__).resolve().parents[2]


def load_repo_dotenv(*, force: bool = False) -> None:
    """从 ``<repo>/.env`` 注入环境变量。

    仅当某键未设置或值为纯空白时写入，避免覆盖已在 shell 中设置的非空 export。
    """
    global _LOADED
    if _LOADED and not force:
        return
    env_path = repo_root() / ".env"
    if not env_path.is_file():
        _LOADED = True
        return
    try:
        raw = env_path.read_text(encoding="utf-8")
    except OSError:
        _LOADED = True
        return
    if raw.startswith("\ufeff"):
        raw = raw[1:]
    applied = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not key:
            continue
        cur = os.environ.get(key)
        if cur is not None and str(cur).strip() != "":
            continue
        os.environ[key] = value
        applied += 1
    if applied:
        _logger.info(
            "已从 %s 注入 %d 个环境变量（仅补齐未设置或为空的键）",
            env_path,
            applied,
        )
    _LOADED = True
