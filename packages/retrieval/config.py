from __future__ import annotations

from dataclasses import dataclass

# 兼容层说明：
# retrieval 仍保留原配置入口，内部 env 解析已经统一委托给 packages.core.config。
# 迁移期建议新能力直接复用 core 配置工具，避免重复实现。
from packages.core.config import (
    env_bool,
    env_float,
    env_float_or_none,
    env_int,
    env_str,
    env_str_or_none,
)
from packages.retrieval.constants import (
    DEFAULT_AB_TEST_B_RATIO,
    DEFAULT_AB_TEST_ENABLED,
    DEFAULT_ADAPTIVE_FALLBACK_FLOOR,
    DEFAULT_CANDIDATE_MULTIPLIER,
    DEFAULT_CROSS_ENCODER_TIMEOUT,
    DEFAULT_ENABLE_HYBRID,
    DEFAULT_ENABLE_QUERY_REWRITE,
    DEFAULT_ENABLE_RERANK,
    DEFAULT_FAISS_METRIC,
    DEFAULT_HYBRID_KEYWORD_WEIGHT,
    DEFAULT_HYBRID_VECTOR_WEIGHT,
    DEFAULT_MILVUS_COLLECTION,
    DEFAULT_MILVUS_URI,
    DEFAULT_QDRANT_COLLECTION,
    DEFAULT_QDRANT_URL,
    DEFAULT_RERANK_BACKEND,
    DEFAULT_RERANK_CANONICAL_FACT_BOOST,
    DEFAULT_RERANK_KEYWORD_WEIGHT,
    DEFAULT_RERANK_RECENCY_WEIGHT,
    DEFAULT_RERANK_VECTOR_WEIGHT,
    DEFAULT_RRF_K,
    DEFAULT_TOP_K,
    DEFAULT_VECTOR_BACKEND,
    DEFAULT_VECTOR_DIM,
)


@dataclass(frozen=True)
class HybridRuntimeConfig:
    candidate_multiplier: int = DEFAULT_CANDIDATE_MULTIPLIER
    rrf_k: int = DEFAULT_RRF_K
    vector_weight: float = DEFAULT_HYBRID_VECTOR_WEIGHT
    keyword_weight: float = DEFAULT_HYBRID_KEYWORD_WEIGHT


@dataclass(frozen=True)
class CrossEncoderRuntimeConfig:
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    timeout_seconds: float = DEFAULT_CROSS_ENCODER_TIMEOUT


@dataclass(frozen=True)
class ABTestRuntimeConfig:
    enabled: bool = DEFAULT_AB_TEST_ENABLED
    b_ratio: float = DEFAULT_AB_TEST_B_RATIO


@dataclass(frozen=True)
class RerankRuntimeConfig:
    backend: str = DEFAULT_RERANK_BACKEND
    vector_weight: float = DEFAULT_RERANK_VECTOR_WEIGHT
    keyword_weight: float = DEFAULT_RERANK_KEYWORD_WEIGHT
    recency_weight: float = DEFAULT_RERANK_RECENCY_WEIGHT
    canonical_fact_boost: float = DEFAULT_RERANK_CANONICAL_FACT_BOOST
    cross_encoder: CrossEncoderRuntimeConfig = CrossEncoderRuntimeConfig()
    ab_test: ABTestRuntimeConfig = ABTestRuntimeConfig()


@dataclass(frozen=True)
class VectorBackendRuntimeConfig:
    backend: str = DEFAULT_VECTOR_BACKEND
    dimension: int = DEFAULT_VECTOR_DIM
    faiss_metric: str = DEFAULT_FAISS_METRIC
    milvus_uri: str = DEFAULT_MILVUS_URI
    milvus_collection: str = DEFAULT_MILVUS_COLLECTION
    qdrant_url: str = DEFAULT_QDRANT_URL
    qdrant_collection: str = DEFAULT_QDRANT_COLLECTION


@dataclass(frozen=True)
class RetrievalRuntimeConfig:
    top_k: int = DEFAULT_TOP_K
    max_distance: float | None = None
    fallback_max_distance: float | None = None
    adaptive_fallback_floor: float = DEFAULT_ADAPTIVE_FALLBACK_FLOOR

    enable_query_rewrite: bool = DEFAULT_ENABLE_QUERY_REWRITE
    enable_hybrid: bool = DEFAULT_ENABLE_HYBRID
    enable_rerank: bool = DEFAULT_ENABLE_RERANK
    query_rewrite_backend: str = "rule"
    keyword_backend: str = "sql_bm25"
    fusion_backend: str = "rrf"
    hybrid_backend: str = "pipeline"

    hybrid: HybridRuntimeConfig = HybridRuntimeConfig()
    rerank: RerankRuntimeConfig = RerankRuntimeConfig()
    vector: VectorBackendRuntimeConfig = VectorBackendRuntimeConfig()

    @classmethod
    def from_env(cls) -> "RetrievalRuntimeConfig":
        ab_enabled = env_bool("WRITER_RETRIEVAL_AB_TEST_ENABLED", DEFAULT_AB_TEST_ENABLED)
        ab_ratio = env_float(
            "WRITER_RETRIEVAL_AB_TEST_B_RATIO",
            DEFAULT_AB_TEST_B_RATIO,
            minimum=0.0,
            maximum=1.0,
        )

        return cls(
            top_k=env_int("WRITER_RETRIEVAL_TOP_K", DEFAULT_TOP_K),
            max_distance=env_float_or_none("WRITER_RETRIEVAL_MAX_DISTANCE", None),
            fallback_max_distance=env_float_or_none(
                "WRITER_RETRIEVAL_FALLBACK_MAX_DISTANCE",
                None,
            ),
            adaptive_fallback_floor=env_float(
                "WRITER_RETRIEVAL_ADAPTIVE_FALLBACK_FLOOR",
                DEFAULT_ADAPTIVE_FALLBACK_FLOOR,
            ),
            enable_query_rewrite=env_bool(
                "WRITER_RETRIEVAL_ENABLE_QUERY_REWRITE",
                DEFAULT_ENABLE_QUERY_REWRITE,
            ),
            enable_hybrid=env_bool(
                "WRITER_RETRIEVAL_ENABLE_HYBRID",
                DEFAULT_ENABLE_HYBRID,
            ),
            enable_rerank=env_bool(
                "WRITER_RETRIEVAL_ENABLE_RERANK",
                DEFAULT_ENABLE_RERANK,
            ),
            query_rewrite_backend=env_str(
                "WRITER_RETRIEVAL_QUERY_REWRITE_BACKEND",
                "rule",
            ),
            keyword_backend=env_str(
                "WRITER_RETRIEVAL_KEYWORD_BACKEND",
                "sql_bm25",
            ),
            fusion_backend=env_str(
                "WRITER_RETRIEVAL_FUSION_BACKEND",
                "rrf",
            ),
            hybrid_backend=env_str(
                "WRITER_RETRIEVAL_HYBRID_BACKEND",
                "pipeline",
            ),
            hybrid=HybridRuntimeConfig(
                candidate_multiplier=env_int(
                    "WRITER_RETRIEVAL_CANDIDATE_MULTIPLIER",
                    DEFAULT_CANDIDATE_MULTIPLIER,
                ),
                rrf_k=env_int("WRITER_RETRIEVAL_RRF_K", DEFAULT_RRF_K),
                vector_weight=env_float(
                    "WRITER_RETRIEVAL_HYBRID_VECTOR_WEIGHT",
                    DEFAULT_HYBRID_VECTOR_WEIGHT,
                ),
                keyword_weight=env_float(
                    "WRITER_RETRIEVAL_HYBRID_KEYWORD_WEIGHT",
                    DEFAULT_HYBRID_KEYWORD_WEIGHT,
                ),
            ),
            rerank=RerankRuntimeConfig(
                backend=env_str(
                    "WRITER_RETRIEVAL_RERANK_BACKEND",
                    DEFAULT_RERANK_BACKEND,
                ),
                vector_weight=env_float(
                    "WRITER_RETRIEVAL_RERANK_VECTOR_WEIGHT",
                    DEFAULT_RERANK_VECTOR_WEIGHT,
                ),
                keyword_weight=env_float(
                    "WRITER_RETRIEVAL_RERANK_KEYWORD_WEIGHT",
                    DEFAULT_RERANK_KEYWORD_WEIGHT,
                ),
                recency_weight=env_float(
                    "WRITER_RETRIEVAL_RERANK_RECENCY_WEIGHT",
                    DEFAULT_RERANK_RECENCY_WEIGHT,
                ),
                canonical_fact_boost=env_float(
                    "WRITER_RETRIEVAL_RERANK_CANONICAL_FACT_BOOST",
                    DEFAULT_RERANK_CANONICAL_FACT_BOOST,
                ),
                cross_encoder=CrossEncoderRuntimeConfig(
                    base_url=env_str_or_none(
                        "WRITER_RERANK_SERVICE_BASE_URL",
                        None,
                    ),
                    api_key=env_str_or_none("WRITER_RERANK_SERVICE_API_KEY", None),
                    model=env_str_or_none("WRITER_RERANK_SERVICE_MODEL", None),
                    timeout_seconds=env_float(
                        "WRITER_RERANK_SERVICE_TIMEOUT",
                        DEFAULT_CROSS_ENCODER_TIMEOUT,
                    ),
                ),
                ab_test=ABTestRuntimeConfig(
                    enabled=ab_enabled,
                    b_ratio=ab_ratio,
                ),
            ),
            vector=VectorBackendRuntimeConfig(
                backend=env_str("WRITER_RETRIEVAL_VECTOR_BACKEND", DEFAULT_VECTOR_BACKEND),
                dimension=env_int("WRITER_RETRIEVAL_VECTOR_DIM", DEFAULT_VECTOR_DIM),
                faiss_metric=env_str("WRITER_RETRIEVAL_FAISS_METRIC", DEFAULT_FAISS_METRIC),
                milvus_uri=env_str("WRITER_RETRIEVAL_MILVUS_URI", DEFAULT_MILVUS_URI),
                milvus_collection=env_str(
                    "WRITER_RETRIEVAL_MILVUS_COLLECTION",
                    DEFAULT_MILVUS_COLLECTION,
                ),
                qdrant_url=env_str("WRITER_RETRIEVAL_QDRANT_URL", DEFAULT_QDRANT_URL),
                qdrant_collection=env_str(
                    "WRITER_RETRIEVAL_QDRANT_COLLECTION",
                    DEFAULT_QDRANT_COLLECTION,
                ),
            ),
        )
