from __future__ import annotations

from collections.abc import Iterable
import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


_DEFAULT_DATABASE_URL = "postgresql+psycopg2://addy:sf123123@localhost:5432/writer_agent_db"


def create_engine_with_driver_fallback(db_url: str, *, echo: bool = False) -> Engine:
    tried: list[str] = []
    last_exc: Exception | None = None
    for candidate in _candidate_urls(db_url):
        tried.append(candidate)
        try:
            return create_engine(candidate, echo=echo)
        except (ModuleNotFoundError, ImportError) as exc:
            last_exc = exc
            continue

    tried_msg = " | ".join(tried)
    hint = (
        "请安装任一 PostgreSQL 驱动：`pip install psycopg2-binary` "
        "或 `pip install psycopg` 或 `pip install pg8000`"
    )
    raise RuntimeError(f"无法创建数据库引擎，已尝试 URL: {tried_msg}。{hint}") from last_exc


def create_engine_from_env() -> Engine:
    db_url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
    env_name = os.environ.get("WRITER_ENV", "").strip().lower()
    is_prod = env_name in {"prod", "production"}
    if is_prod and (not os.environ.get("DATABASE_URL") or db_url == _DEFAULT_DATABASE_URL):
        raise RuntimeError("生产环境禁止使用默认 DATABASE_URL，请显式配置环境变量 DATABASE_URL")
    echo = os.environ.get("SQL_ECHO", "").lower() in ("1", "true", "yes")
    return create_engine_with_driver_fallback(db_url, echo=echo)


def create_session_factory(engine: Engine | None = None):
    effective_engine = engine or create_engine_from_env()
    return sessionmaker(bind=effective_engine, autoflush=False, autocommit=False, class_=Session)


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
