from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import bindparam, cast, select

from packages.core.utils import summarize_text_extractive
from .base import BaseRepository
from packages.storage.postgres.models.memory_fact import MemoryFact
from packages.storage.postgres.models.memory_mention import MemoryMention
from packages.storage.postgres.types import PgVector
from packages.storage.postgres.vector_settings import MEMORY_EMBEDDING_DIM


@dataclass(frozen=True)
class FactUpsertResult:
    fact: MemoryFact
    mention: MemoryMention
    created_new_fact: bool
    created_new_mention: bool
    semantic_distance: float | None


class MemoryFactRepository(BaseRepository):
    """
    规范事实 + 原始提及的双层仓储。

    核心策略：
    1. 先 exact dedup（normalized hash）。
    2. 再 semantic dedup（向量距离阈值）。
    3. 无命中才创建新事实。
    """

    _EMBEDDING_DIM = MEMORY_EMBEDDING_DIM
    _MULTI_SPACE_RE = re.compile(r"\s+")

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _normalize_text(cls, text: str) -> str:
        if not isinstance(text, str):
            raise ValueError("text 必须是字符串")
        normalized = text.strip().lower()
        normalized = cls._MULTI_SPACE_RE.sub(" ", normalized)
        return normalized

    @staticmethod
    def _hash_text(normalized_text: str) -> str:
        return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()

    @staticmethod
    def _vector_to_pg(value: list[float]) -> str:
        return "[" + ",".join(str(float(x)) for x in value) + "]"

    def _validate_embedding(self, embedding: list[float]) -> None:
        if len(embedding) != self._EMBEDDING_DIM:
            raise ValueError(
                f"embedding 维度错误：期望 {self._EMBEDDING_DIM}，实际 {len(embedding)}"
            )

    def _find_exact_fact(self, project_id, canonical_hash: str) -> MemoryFact | None:
        stmt = select(MemoryFact).where(
            MemoryFact.project_id == project_id,
            MemoryFact.canonical_hash == canonical_hash,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def _find_best_semantic_fact(
        self,
        *,
        project_id,
        embedding: list[float],
        semantic_threshold: float,
    ) -> tuple[MemoryFact, float] | None:
        vector_str = self._vector_to_pg(embedding)
        query_vector = cast(
            bindparam("query_embedding", value=vector_str),
            PgVector(self._EMBEDDING_DIM),
        )
        distance_expr = MemoryFact.embedding.op("<=>")(query_vector).label("distance")

        stmt = (
            select(MemoryFact, distance_expr)
            .where(MemoryFact.project_id == project_id)
            .order_by(distance_expr.asc())
            .limit(1)
        )
        row = self.db.execute(stmt).first()
        if not row:
            return None

        fact, distance = row
        distance = float(distance)
        if distance > float(semantic_threshold):
            return None
        return fact, distance

    def _upsert_mention(
        self,
        *,
        project_id,
        fact_id,
        source_type: str,
        source_id,
        chunk_type: str | None,
        raw_text: str,
        mention_hash: str,
        metadata_json: dict,
        semantic_distance: float | None,
    ) -> tuple[MemoryMention, bool]:
        stmt = select(MemoryMention).where(
            MemoryMention.project_id == project_id,
            MemoryMention.fact_id == fact_id,
            MemoryMention.mention_hash == mention_hash,
            MemoryMention.source_type == source_type,
            MemoryMention.source_id == source_id,
            MemoryMention.chunk_type == chunk_type,
        )
        mention = self.db.execute(stmt).scalar_one_or_none()

        now = self._now()
        if mention:
            mention.occurrence_count += 1
            mention.last_seen_at = now
            if semantic_distance is not None:
                mention.distance_to_fact = float(semantic_distance)
            return mention, False

        mention = MemoryMention(
            project_id=project_id,
            fact_id=fact_id,
            source_type=source_type,
            source_id=source_id,
            chunk_type=chunk_type,
            raw_text=raw_text,
            mention_hash=mention_hash,
            distance_to_fact=semantic_distance,
            metadata_json=metadata_json or {},
            occurrence_count=1,
            first_seen_at=now,
            last_seen_at=now,
        )
        self.db.add(mention)
        return mention, True

    def get(self, fact_id) -> MemoryFact | None:
        return self.db.get(MemoryFact, fact_id)

    def list_forgetting_candidates(
        self,
        *,
        project_id,
        limit: int = 200,
    ) -> list[MemoryFact]:
        if limit <= 0:
            return []
        stmt = (
            select(MemoryFact)
            .where(MemoryFact.project_id == project_id)
            .order_by(
                MemoryFact.last_seen_at.asc(),
                MemoryFact.mention_count.asc(),
            )
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def mark_forgetting_stage(
        self,
        *,
        fact_id,
        stage: str,
        reason: str,
        score: float,
        now: datetime | None = None,
        auto_commit: bool = True,
    ) -> MemoryFact | None:
        fact = self.get(fact_id)
        if fact is None:
            return None

        now = now or self._now()
        metadata = dict(fact.metadata_json or {})
        metadata.update(
            {
                "forgetting_stage": stage,
                "forgetting_reason": reason,
                "forgetting_score": float(score),
                "forgotten_at": now.isoformat().replace("+00:00", "Z"),
            }
        )
        fact.metadata_json = metadata

        if auto_commit:
            self.db.commit()
            self.db.refresh(fact)
        else:
            self.db.flush()
        return fact

    def clear_forgetting_stage(
        self,
        *,
        fact_id,
        auto_commit: bool = True,
    ) -> MemoryFact | None:
        fact = self.get(fact_id)
        if fact is None:
            return None

        metadata = dict(fact.metadata_json or {})
        for key in (
            "forgetting_stage",
            "forgetting_reason",
            "forgetting_score",
            "forgotten_at",
        ):
            metadata.pop(key, None)
        fact.metadata_json = metadata

        if auto_commit:
            self.db.commit()
            self.db.refresh(fact)
        else:
            self.db.flush()
        return fact

    def delete_fact(self, fact_id, *, auto_commit: bool = True) -> bool:
        fact = self.get(fact_id)
        if fact is None:
            return False
        self.db.delete(fact)
        if auto_commit:
            self.db.commit()
        else:
            self.db.flush()
        return True

    def upsert_fact_with_mention(
        self,
        *,
        project_id,
        source_type: str,
        source_id,
        chunk_type: str | None,
        raw_text: str,
        embedding: list[float],
        metadata_json: dict | None = None,
        semantic_threshold: float = 0.12,
        auto_commit: bool = True,
    ) -> FactUpsertResult:
        """
        双层去重写入：
        1. exact dedup（hash）
        2. semantic dedup（距离阈值）
        3. mention upsert（同源重复聚合计数）
        """
        if not source_type or not isinstance(source_type, str):
            raise ValueError("source_type 不能为空字符串")
        self._validate_embedding(embedding)

        normalized_text = self._normalize_text(raw_text)
        if not normalized_text:
            raise ValueError("raw_text 不能为空")

        canonical_hash = self._hash_text(normalized_text)
        mention_hash = canonical_hash
        metadata_json = metadata_json or {}
        now = self._now()

        fact = self._find_exact_fact(project_id=project_id, canonical_hash=canonical_hash)
        created_new_fact = False
        semantic_distance: float | None = 0.0 if fact else None

        if fact is None:
            semantic_match = self._find_best_semantic_fact(
                project_id=project_id,
                embedding=embedding,
                semantic_threshold=semantic_threshold,
            )
            if semantic_match:
                fact, semantic_distance = semantic_match
                fact.mention_count += 1
                fact.last_seen_at = now
                if not (fact.summary_text or "").strip():
                    fact.summary_text = summarize_text_extractive(
                        fact.canonical_text,
                        target_tokens=96,
                        min_sentences=1,
                        max_sentences=3,
                    )
                self.clear_forgetting_stage(fact_id=fact.id, auto_commit=False)
            else:
                fact = MemoryFact(
                    project_id=project_id,
                    canonical_text=raw_text.strip(),
                    summary_text=summarize_text_extractive(
                        raw_text.strip(),
                        target_tokens=96,
                        min_sentences=1,
                        max_sentences=3,
                    ),
                    canonical_hash=canonical_hash,
                    embedding=embedding,
                    metadata_json=metadata_json,
                    mention_count=1,
                    first_seen_at=now,
                    last_seen_at=now,
                )
                self.db.add(fact)
                self.db.flush()
                created_new_fact = True
                semantic_distance = 0.0
        else:
            fact.mention_count += 1
            fact.last_seen_at = now
            if not (fact.summary_text or "").strip():
                fact.summary_text = summarize_text_extractive(
                    fact.canonical_text,
                    target_tokens=96,
                    min_sentences=1,
                    max_sentences=3,
                )
            self.clear_forgetting_stage(fact_id=fact.id, auto_commit=False)

        mention, created_new_mention = self._upsert_mention(
            project_id=project_id,
            fact_id=fact.id,
            source_type=source_type,
            source_id=source_id,
            chunk_type=chunk_type,
            raw_text=raw_text,
            mention_hash=mention_hash,
            metadata_json=metadata_json,
            semantic_distance=semantic_distance,
        )

        if auto_commit:
            self.db.commit()
            self.db.refresh(fact)
            self.db.refresh(mention)
        else:
            self.db.flush()

        return FactUpsertResult(
            fact=fact,
            mention=mention,
            created_new_fact=created_new_fact,
            created_new_mention=created_new_mention,
            semantic_distance=semantic_distance,
        )
