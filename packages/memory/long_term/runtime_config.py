from __future__ import annotations

from dataclasses import dataclass

# 兼容层说明：
# memory 主链继续保持原有 RuntimeConfig 入口，对外签名不变；
# 底层 env 解析已迁移至 packages.core.config 统一实现。
from packages.core.config import env_bool, env_float, env_int, env_str
from packages.retrieval.config import RetrievalRuntimeConfig


@dataclass(frozen=True)
class IngestionRuntimeConfig:
    chunk_size: int = 500
    chunk_overlap: int = 80
    embedding_batch_size: int = 32
    replace_existing_by_default: bool = True
    semantic_dedup_threshold: float = 0.12
    summary_target_tokens: int = 96


@dataclass(frozen=True)
class ContextCompressionRuntimeConfig:
    enable_llm: bool = True
    llm_trigger_ratio: float = 1.6
    llm_min_gain_ratio: float = 0.12
    llm_max_input_chars: int = 16000
    llm_max_items: int = 2
    context_token_budget_default: int = 8000
    context_min_relevance_score: float = 0.58
    context_relative_score_floor: float = 0.72
    context_min_keep_rows: int = 3
    context_max_rows: int = 32


@dataclass(frozen=True)
class ObservabilityRuntimeConfig:
    logger_name: str = "writeragent.memory"
    enable_logging: bool = True


@dataclass(frozen=True)
class ForgettingRuntimeConfig:
    enable: bool = True
    cooling_days: int = 7
    suppress_days: int = 30
    archive_days: int = 90
    delete_days: int = 180
    min_mentions_to_keep: int = 3
    run_limit: int = 200


@dataclass(frozen=True)
class MemoryRuntimeConfig:
    ingestion: IngestionRuntimeConfig = IngestionRuntimeConfig()
    context_compression: ContextCompressionRuntimeConfig = ContextCompressionRuntimeConfig()
    retrieval: RetrievalRuntimeConfig = RetrievalRuntimeConfig()
    observability: ObservabilityRuntimeConfig = ObservabilityRuntimeConfig()
    forgetting: ForgettingRuntimeConfig = ForgettingRuntimeConfig()

    @classmethod
    def from_env(cls) -> "MemoryRuntimeConfig":
        retrieval = RetrievalRuntimeConfig.from_env()
        ingestion = IngestionRuntimeConfig(
            chunk_size=env_int(
                "WRITER_MEMORY_CHUNK_SIZE",
                500,
            ),
            chunk_overlap=env_int(
                "WRITER_MEMORY_CHUNK_OVERLAP",
                80,
            ),
            embedding_batch_size=env_int(
                "WRITER_MEMORY_INGEST_EMBEDDING_BATCH_SIZE",
                32,
            ),
            replace_existing_by_default=env_bool(
                "WRITER_MEMORY_INGEST_REPLACE_EXISTING_BY_DEFAULT",
                True,
            ),
            semantic_dedup_threshold=env_float(
                "WRITER_MEMORY_SEMANTIC_DEDUP_THRESHOLD",
                0.12,
            ),
            summary_target_tokens=env_int(
                "WRITER_MEMORY_SUMMARY_TARGET_TOKENS",
                96,
            ),
        )
        observability = ObservabilityRuntimeConfig(
            logger_name=env_str("WRITER_MEMORY_LOGGER_NAME", "writeragent.memory"),
            enable_logging=env_bool("WRITER_MEMORY_ENABLE_LOGGING", True),
        )
        context_compression = ContextCompressionRuntimeConfig(
            enable_llm=env_bool(
                "WRITER_MEMORY_CONTEXT_COMPRESS_ENABLE_LLM",
                True,
            ),
            llm_trigger_ratio=env_float(
                "WRITER_MEMORY_CONTEXT_COMPRESS_LLM_TRIGGER_RATIO",
                1.6,
            ),
            llm_min_gain_ratio=env_float(
                "WRITER_MEMORY_CONTEXT_COMPRESS_LLM_MIN_GAIN_RATIO",
                0.12,
            ),
            llm_max_input_chars=env_int(
                "WRITER_MEMORY_CONTEXT_COMPRESS_LLM_MAX_INPUT_CHARS",
                16000,
            ),
            llm_max_items=env_int(
                "WRITER_MEMORY_CONTEXT_COMPRESS_LLM_MAX_ITEMS",
                2,
            ),
            context_token_budget_default=env_int(
                "WRITER_MEMORY_CONTEXT_TOKEN_BUDGET_DEFAULT",
                10000,
            ),
            context_min_relevance_score=env_float(
                "WRITER_MEMORY_CONTEXT_MIN_RELEVANCE_SCORE",
                0.58,
            ),
            context_relative_score_floor=env_float(
                "WRITER_MEMORY_CONTEXT_RELATIVE_SCORE_FLOOR",
                0.72,
            ),
            context_min_keep_rows=env_int(
                "WRITER_MEMORY_CONTEXT_MIN_KEEP_ROWS",
                3,
            ),
            context_max_rows=env_int(
                "WRITER_MEMORY_CONTEXT_MAX_ROWS",
                32,
            ),
        )
        forgetting = ForgettingRuntimeConfig(
            enable=env_bool("WRITER_MEMORY_FORGET_ENABLE", True),
            cooling_days=env_int("WRITER_MEMORY_FORGET_COOLING_DAYS", 7),
            suppress_days=env_int("WRITER_MEMORY_FORGET_SUPPRESS_DAYS", 30),
            archive_days=env_int("WRITER_MEMORY_FORGET_ARCHIVE_DAYS", 90),
            delete_days=env_int("WRITER_MEMORY_FORGET_DELETE_DAYS", 180),
            min_mentions_to_keep=env_int("WRITER_MEMORY_FORGET_MIN_MENTION_KEEP", 3),
            run_limit=env_int("WRITER_MEMORY_FORGET_RUN_LIMIT", 200),
        )

        return cls(
            ingestion=ingestion,
            context_compression=context_compression,
            retrieval=retrieval,
            observability=observability,
            forgetting=forgetting,
        )
