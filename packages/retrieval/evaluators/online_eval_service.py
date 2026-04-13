from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import uuid4

from packages.storage.postgres.repositories.retrieval_eval_repository import (
    RetrievalDailyStatSnapshot,
    RetrievalEvalRepository,
)


@dataclass(frozen=True)
class EvalAssignment:
    request_id: str
    variant: str


class OnlineEvalService:
    """在线评测服务（A/B 分配 + 事件落库 + 聚合读取）。"""

    def __init__(self, repo: RetrievalEvalRepository) -> None:
        self.repo = repo

    def assign_variant(
        self,
        *,
        project_id,
        user_id: str | None,
        query: str,
        b_ratio: float = 0.5,
    ) -> EvalAssignment:
        ratio = min(max(float(b_ratio), 0.0), 1.0)
        identity = user_id or "anonymous"
        key = f"{project_id}:{identity}:{query}".encode("utf-8")
        digest = hashlib.sha256(key).hexdigest()
        bucket = int(digest[:8], 16) / 0xFFFFFFFF
        variant = "B" if bucket < ratio else "A"
        return EvalAssignment(request_id=str(uuid4()), variant=variant)

    def record_impression(
        self,
        *,
        project_id,
        request_id: str,
        user_id: str | None,
        query: str,
        variant: str,
        rerank_backend: str | None,
        impressed_doc_ids: list[str],
        context_json: dict | None = None,
    ) -> None:
        self.repo.create_impression(
            project_id=project_id,
            request_id=request_id,
            user_id=user_id,
            query=query,
            variant=variant,
            rerank_backend=rerank_backend,
            impressed_doc_ids=impressed_doc_ids,
            context_json=context_json or {},
        )

    def record_feedback(
        self,
        *,
        project_id,
        request_id: str,
        user_id: str | None,
        clicked_doc_id: str | None,
        clicked: bool = True,
    ) -> bool:
        return self.repo.record_feedback(
            project_id=project_id,
            request_id=request_id,
            user_id=user_id,
            clicked_doc_id=clicked_doc_id,
            clicked=clicked,
        )

    def get_daily_stats(self, *, project_id) -> list[RetrievalDailyStatSnapshot]:
        return self.repo.get_daily_stats(project_id=project_id)

