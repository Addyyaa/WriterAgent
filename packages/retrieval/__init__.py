from packages.retrieval.config import RetrievalRuntimeConfig
from packages.retrieval.errors import (
    RetrievalConfigError,
    RetrievalDataError,
    RetrievalError,
    RetrievalInputError,
    RetrievalTimeoutError,
    RetrieverUnavailableError,
)
from packages.retrieval.types import FilterExpr, RetrievalDoc, RetrievalOptions, ScoredDoc


def __getattr__(name: str):
    if name == "RetrievalPipeline":
        from packages.retrieval.pipeline import RetrievalPipeline

        return RetrievalPipeline
    raise AttributeError(name)

__all__ = [
    "FilterExpr",
    "RetrievalDoc",
    "RetrievalError",
    "RetrievalConfigError",
    "RetrievalDataError",
    "RetrievalInputError",
    "RetrievalOptions",
    "RetrievalPipeline",
    "RetrievalRuntimeConfig",
    "RetrievalTimeoutError",
    "RetrieverUnavailableError",
    "ScoredDoc",
]
