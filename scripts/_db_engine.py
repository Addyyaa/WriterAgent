from __future__ import annotations

from typing import Iterable

from sqlalchemy import create_engine


def create_engine_with_driver_fallback(db_url: str, *, echo: bool = False):
    """
    创建 SQLAlchemy Engine，并在 PostgreSQL 驱动缺失时自动回退。

    回退顺序示例（输入是 psycopg2 URL 时）：
    1) postgresql+psycopg2://...
    2) postgresql+psycopg://...
    3) postgresql+pg8000://...
    4) postgresql://...
    """
    tried: list[str] = []
    last_exc: Exception | None = None

    for candidate in _candidate_urls(db_url):
        tried.append(candidate)
        try:
            return create_engine(candidate, echo=echo)
        except (ModuleNotFoundError, ImportError) as exc:
            # 驱动模块不存在时继续尝试下一个方言驱动。
            last_exc = exc
            continue

    tried_msg = " | ".join(tried)
    hint = "请安装任一 PostgreSQL 驱动：`pip install psycopg2-binary` 或 `pip install psycopg` 或 `pip install pg8000`"
    raise RuntimeError(
        f"无法创建数据库引擎，已尝试 URL: {tried_msg}。{hint}"
    ) from last_exc


def _candidate_urls(db_url: str) -> Iterable[str]:
    yield db_url

    if db_url.startswith("postgresql+psycopg2://"):
        yield db_url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
        yield db_url.replace("postgresql+psycopg2://", "postgresql+pg8000://", 1)
        yield db_url.replace("postgresql+psycopg2://", "postgresql://", 1)
        return

    if db_url.startswith("postgresql+psycopg://"):
        yield db_url.replace("postgresql+psycopg://", "postgresql+psycopg2://", 1)
        yield db_url.replace("postgresql+psycopg://", "postgresql+pg8000://", 1)
        yield db_url.replace("postgresql+psycopg://", "postgresql://", 1)
        return

    if db_url.startswith("postgresql+pg8000://"):
        yield db_url.replace("postgresql+pg8000://", "postgresql+psycopg://", 1)
        yield db_url.replace("postgresql+pg8000://", "postgresql+psycopg2://", 1)
        yield db_url.replace("postgresql+pg8000://", "postgresql://", 1)
        return

    if db_url.startswith("postgresql://"):
        yield db_url.replace("postgresql://", "postgresql+psycopg://", 1)
        yield db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        yield db_url.replace("postgresql://", "postgresql+pg8000://", 1)
