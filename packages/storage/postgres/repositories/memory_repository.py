from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re

from sqlalchemy import bindparam, case, cast, delete, func, select

from .base import BaseRepository
from packages.memory.long_term.temporal import (
    SOURCE_TIMESTAMP_KEY,
    normalize_source_timestamp,
)
from packages.storage.postgres.models.memory_chunk import MemoryChunk
from packages.storage.postgres.types import PgVector
from packages.storage.postgres.vector_settings import MEMORY_EMBEDDING_DIM


class MemoryChunkRepository(BaseRepository):
    _EMBEDDING_DIM = MEMORY_EMBEDDING_DIM
    _ALLOWED_EMBEDDING_STATUS = {
        "pending",
        "queued",
        "processing",
        "retrying",
        "done",
        "failed",
        "stale",
    }
    _ALLOWED_EMBEDDING_TRANSITIONS: dict[str, set[str]] = {
        "pending": {"queued", "processing", "failed"},
        "queued": {"pending", "processing", "failed"},
        "processing": {"done", "failed"},
        "retrying": {"processing", "failed"},
        "done": {"stale"},
        "stale": {"queued", "processing", "pending"},
        "failed": {"retrying", "pending"},
    }
    _ALLOWED_LIST_SORT = {
        "created_at_desc",
        "source_timestamp_desc",
        "source_timestamp_asc",
    }
    _ALLOWED_SIMILARITY_SORT = {
        "distance",
        "distance_then_source_timestamp_desc",
        "source_timestamp_desc",
        "source_timestamp_asc",
    }
    _ALLOWED_KEYWORD_SORT = {
        "keyword_score_desc",
        "source_timestamp_desc",
        "source_timestamp_asc",
    }
    _CJK_SEQ_RE = re.compile(r"[\u4e00-\u9fff]+")
    _CJK_NOISE_TERMS = {"什么", "哪些", "怎么", "如何", "为什么", "是否", "一下"}

    @staticmethod
    def _vector_to_pg(value: list[float]) -> str:
        """
        把 Python list[float] 转成 pgvector 可识别的字符串格式：
        [0.1,0.2,0.3]
        """
        return "[" + ",".join(str(float(x)) for x in value) + "]"

    def create_chunks(
        self,
        project_id,
        chunks: list[dict],
    ) -> list[MemoryChunk]:
        """
        chunks 结构示例：
        [
            {
                "source_type": "chapter",
                "source_id": uuid_xxx,
                "chunk_type": "paragraph",
                "text": "...",
                "metadata_json": {...},
                "embedding": [...],
                "embedding_status": "done",
            }
        ]
        """
        rows: list[MemoryChunk] = []

        for item in chunks:
            embedding = item.get("embedding")
            if embedding is not None:
                self._validate_embedding(embedding)

            embedding_status = item.get("embedding_status", "pending")
            self._validate_embedding_status(embedding_status)
            metadata_json = self._normalize_metadata_json(item.get("metadata_json", {}))

            row = MemoryChunk(
                project_id=project_id,
                source_type=item.get("source_type"),
                source_id=item.get("source_id"),
                chunk_type=item.get("chunk_type"),
                chunk_text=item.get("text"),
                summary_text=item.get("summary_text"),
                metadata_json=metadata_json,
                embedding=embedding,
                embedding_status=embedding_status,
            )
            self.db.add(row)
            rows.append(row)

        self.db.commit()

        for row in rows:
            self.db.refresh(row) # 刷新行对象，获取数据库生成的 ID 等属性

        return rows

    def get(self, chunk_id) -> MemoryChunk | None:
        return self.db.get(MemoryChunk, chunk_id)

    def list_by_project(
        self,
        project_id,
        *,
        limit: int = 100,
        offset: int = 0,
        source_type: str | None = None,
        chunk_type: str | None = None,
        embedding_status: str | None = None,
        sort_by: str = "created_at_desc",
        source_timestamp_gte: str | datetime | None = None,
        source_timestamp_lte: str | datetime | None = None,
    ) -> list[MemoryChunk]:
        if limit <= 0:
            return []
        self._validate_list_sort(sort_by)
        source_ts_expr = MemoryChunk.metadata_json[SOURCE_TIMESTAMP_KEY].astext

        stmt = select(MemoryChunk).where(MemoryChunk.project_id == project_id)

        if source_type is not None:
            stmt = stmt.where(MemoryChunk.source_type == source_type)
        if chunk_type is not None:
            stmt = stmt.where(MemoryChunk.chunk_type == chunk_type)
        if embedding_status is not None:
            self._validate_embedding_status(embedding_status)
            stmt = stmt.where(MemoryChunk.embedding_status == embedding_status)

        if source_timestamp_gte is not None:
            normalized_gte = normalize_source_timestamp(source_timestamp_gte)
            stmt = stmt.where(
                source_ts_expr.isnot(None),
                source_ts_expr >= normalized_gte,
            )
        if source_timestamp_lte is not None:
            normalized_lte = normalize_source_timestamp(source_timestamp_lte)
            stmt = stmt.where(
                source_ts_expr.isnot(None),
                source_ts_expr <= normalized_lte,
            )

        if sort_by == "source_timestamp_desc":
            stmt = stmt.order_by(
                source_ts_expr.desc().nullslast(),
                MemoryChunk.created_at.desc(),
            )
        elif sort_by == "source_timestamp_asc":
            stmt = stmt.order_by(
                source_ts_expr.asc().nullslast(),
                MemoryChunk.created_at.asc(),
            )
        else:
            stmt = stmt.order_by(MemoryChunk.created_at.desc())

        stmt = stmt.limit(limit).offset(max(offset, 0))
        return list(self.db.execute(stmt).scalars().all())

    def update_chunk(self, chunk_id, auto_commit: bool = True, **fields) -> MemoryChunk | None:
        chunk = self.get(chunk_id)
        if not chunk:
            return None

        if "text" in fields:
            fields["chunk_text"] = fields.pop("text")

        allowed = {
            "source_type",
            "source_id",
            "chunk_type",
            "chunk_text",
            "summary_text",
            "metadata_json",
            "embedding",
            "embedding_status",
        }
        unknown = set(fields) - allowed
        if unknown:
            unknown_keys = ", ".join(sorted(unknown))
            raise ValueError(f"不支持更新的字段: {unknown_keys}")

        if "embedding_status" in fields:
            self._validate_embedding_status(fields["embedding_status"])
        if "embedding" in fields and fields["embedding"] is not None:
            self._validate_embedding(fields["embedding"])
        if "metadata_json" in fields:
            fields["metadata_json"] = self._normalize_metadata_json(fields["metadata_json"])

        for key, value in fields.items():
            setattr(chunk, key, value) # 设置属性，更新数据库

        if auto_commit:
            self.db.commit()
            self.db.refresh(chunk)
        else:
            self.db.flush()
        return chunk

    def delete(self, chunk_id, *, auto_commit: bool = True) -> bool:
        chunk = self.get(chunk_id)
        if not chunk:
            return False

        self.db.delete(chunk)
        if auto_commit:
            self.db.commit()
        else:
            self.db.flush()
        return True

    def delete_by_project(self, project_id, *, auto_commit: bool = True) -> int:
        stmt = delete(MemoryChunk).where(MemoryChunk.project_id == project_id)
        result = self.db.execute(stmt)
        if auto_commit:
            self.db.commit()
        else:
            self.db.flush()
        return int(result.rowcount or 0)

    def delete_by_source(
        self,
        project_id,
        source_type: str,
        source_id,
        *,
        auto_commit: bool = True,
    ) -> int:
        stmt = delete(MemoryChunk).where(
            MemoryChunk.project_id == project_id,
            MemoryChunk.source_type == source_type,
            MemoryChunk.source_id == source_id,
        )
        result = self.db.execute(stmt)
        if auto_commit:
            self.db.commit()
        else:
            self.db.flush()
        return int(result.rowcount or 0)

    def list_by_source(
        self,
        *,
        project_id,
        source_type: str,
        source_id,
        embedding_status: str | None = None,
        limit: int = 500,
    ) -> list[MemoryChunk]:
        if limit <= 0:
            return []

        stmt = (
            select(MemoryChunk)
            .where(
                MemoryChunk.project_id == project_id,
                MemoryChunk.source_type == source_type,
                MemoryChunk.source_id == source_id,
            )
            .order_by(MemoryChunk.created_at.asc())
            .limit(limit)
        )
        if embedding_status is not None:
            self._validate_embedding_status(embedding_status)
            stmt = stmt.where(MemoryChunk.embedding_status == embedding_status)
        return list(self.db.execute(stmt).scalars().all())

    def replace_source_chunks(
        self,
        project_id,
        source_type: str,
        source_id,
        chunks: list[dict],
    ) -> list[MemoryChunk]:
        """
        幂等替换某来源下的所有分块（删除旧分块 + 写入新分块）。
        """
        self.db.execute(
            # 按项目、来源、来源ID删除旧分块，按照id删除不现实，因为不知道id总共有哪些
            delete(MemoryChunk).where(
                MemoryChunk.project_id == project_id,
                MemoryChunk.source_type == source_type,
                MemoryChunk.source_id == source_id,
            )
        )

        rows: list[MemoryChunk] = []
        for item in chunks:
            embedding = item.get("embedding")
            if embedding is not None:
                self._validate_embedding(embedding)

            embedding_status = item.get("embedding_status", "pending")
            self._validate_embedding_status(embedding_status)
            metadata_json = self._normalize_metadata_json(item.get("metadata_json", {}))

            row = MemoryChunk(
                project_id=project_id,
                source_type=source_type,
                source_id=source_id,
                chunk_type=item.get("chunk_type"),
                chunk_text=item.get("text"),
                summary_text=item.get("summary_text"),
                metadata_json=metadata_json,
                embedding=embedding,
                embedding_status=embedding_status,
            )
            self.db.add(row)
            rows.append(row)

        self.db.commit()
        for row in rows:
            self.db.refresh(row)
        return rows

    def list_pending_embeddings(
        self,
        *,
        project_id=None,
        limit: int = 200,
    ) -> list[MemoryChunk]:
        if limit <= 0:
            return []

        stmt = (
            select(MemoryChunk)
            .where(MemoryChunk.embedding_status.in_(("pending", "queued", "retrying")))
            .order_by(MemoryChunk.created_at.asc())
            .limit(limit)
        )
        if project_id is not None:
            stmt = stmt.where(MemoryChunk.project_id == project_id)

        return list(self.db.execute(stmt).scalars().all())

    def mark_embedding_processing(
        self,
        chunk_id,
        *,
        auto_commit: bool = True,
    ) -> MemoryChunk | None:
        return self._set_embedding_state(
            chunk_id,
            "processing",
            auto_commit=auto_commit,
        )

    def mark_embedding_queued(
        self,
        chunk_id,
        *,
        auto_commit: bool = True,
    ) -> MemoryChunk | None:
        return self._set_embedding_state(
            chunk_id,
            "queued",
            auto_commit=auto_commit,
        )

    def mark_embedding_retrying(
        self,
        chunk_id,
        *,
        auto_commit: bool = True,
    ) -> MemoryChunk | None:
        return self._set_embedding_state(
            chunk_id,
            "retrying",
            auto_commit=auto_commit,
        )

    def mark_embedding_stale(
        self,
        chunk_id,
        *,
        auto_commit: bool = True,
    ) -> MemoryChunk | None:
        return self._set_embedding_state(
            chunk_id,
            "stale",
            auto_commit=auto_commit,
        )

    def mark_embedding_done(
        self,
        chunk_id,
        embedding: list[float],
        *,
        auto_commit: bool = True,
    ) -> MemoryChunk | None:
        return self._set_embedding_state(
            chunk_id,
            "done",
            embedding=embedding,
            auto_commit=auto_commit,
        )

    def mark_embedding_failed(
        self,
        chunk_id,
        *,
        auto_commit: bool = True,
    ) -> MemoryChunk | None:
        return self._set_embedding_state(
            chunk_id,
            "failed",
            auto_commit=auto_commit,
        )

    def count_by_project(self, project_id) -> int:
        stmt = (
            select(func.count(MemoryChunk.id))
            .where(MemoryChunk.project_id == project_id)
        )
        return int(self.db.execute(stmt).scalar_one())

    def stats_by_status(self, project_id) -> dict[str, int]:
        stmt = (
            select(MemoryChunk.embedding_status, func.count(MemoryChunk.id))
            .where(MemoryChunk.project_id == project_id)
            .group_by(MemoryChunk.embedding_status)
        )

        stats: dict[str, int] = {status: 0 for status in self._ALLOWED_EMBEDDING_STATUS}
        for status, count in self.db.execute(stmt).all():
            stats[str(status)] = int(count)
        return stats

    def reset_failed_to_pending(
        self,
        *,
        project_id=None,
        limit: int = 200,
    ) -> int:
        if limit <= 0:
            return 0

        stmt = (
            select(MemoryChunk)
            .where(MemoryChunk.embedding_status == "failed")
            .order_by(MemoryChunk.updated_at.asc())
            .limit(limit)
        )
        if project_id is not None:
            stmt = stmt.where(MemoryChunk.project_id == project_id)

        rows = list(self.db.execute(stmt).scalars().all())
        for row in rows:
            row.embedding_status = "pending"
        self.db.commit()
        return len(rows)

    def reset_stale_to_pending(
        self,
        *,
        project_id=None,
        limit: int = 200,
    ) -> int:
        if limit <= 0:
            return 0

        stmt = (
            select(MemoryChunk)
            .where(MemoryChunk.embedding_status == "stale")
            .order_by(MemoryChunk.updated_at.asc())
            .limit(limit)
        )
        if project_id is not None:
            stmt = stmt.where(MemoryChunk.project_id == project_id)

        rows = list(self.db.execute(stmt).scalars().all())
        for row in rows:
            row.embedding_status = "pending"
        self.db.commit()
        return len(rows)

    def reset_processing_to_pending(
        self,
        *,
        project_id=None,
        stale_after_seconds: int = 900,
        limit: int = 200,
    ) -> int:
        if limit <= 0:
            return 0
        if stale_after_seconds < 0:
            raise ValueError("stale_after_seconds 不能小于 0")

        cutoff = datetime.now(tz=timezone.utc) - timedelta(seconds=stale_after_seconds)
        stmt = (
            select(MemoryChunk)
            .where(
                MemoryChunk.embedding_status == "processing",
                MemoryChunk.updated_at <= cutoff,
            )
            .order_by(MemoryChunk.updated_at.asc())
            .limit(limit)
        )
        if project_id is not None:
            stmt = stmt.where(MemoryChunk.project_id == project_id)

        rows = list(self.db.execute(stmt).scalars().all())
        for row in rows:
            row.embedding_status = "pending"
        self.db.commit()
        return len(rows)

    def similarity_search(
        self,
        project_id,
        query_embedding: list[float],
        top_k: int = 5,
        source_type: str | None = None,
        chunk_type: str | None = None,
        max_distance: float | None = None,
        only_done: bool = True,
        exclude_forgetting_stages: tuple[str, ...] | None = (
            "suppressed",
            "archived",
            "deleted",
        ),
        source_timestamp_gte: str | datetime | None = None,
        source_timestamp_lte: str | datetime | None = None,
        sort_by: str = "distance",
    ) -> list[dict]:
        """
        返回最相似的 chunks，包含相似度距离
        使用 pgvector 余弦距离操作符 <=>，越小越相似

        时间语义支持：
        - source_timestamp_gte/lte: 按 metadata_json.source_timestamp 过滤
        - sort_by:
            - distance（默认，兼容旧行为）
            - distance_then_source_timestamp_desc（同等相关性下优先最新）
            - source_timestamp_desc / source_timestamp_asc（按语义时间排序）
        """
        if top_k <= 0:
            return []
        if not query_embedding:
            return []
        self._validate_similarity_sort(sort_by)

        self._validate_embedding(query_embedding)

        vector_str = self._vector_to_pg(query_embedding)
        source_ts_expr = MemoryChunk.metadata_json[SOURCE_TIMESTAMP_KEY].astext
        
        query_vector = cast(
            bindparam("query_embedding", value=vector_str),
            PgVector(self._EMBEDDING_DIM),
        )
        forgetting_stage_expr = MemoryChunk.metadata_json["forgetting_stage"].astext
        distance_expr = MemoryChunk.embedding.op("<=>")(query_vector).label("distance")

        stmt = (
            select(
                MemoryChunk.id,
                MemoryChunk.project_id,
                MemoryChunk.source_type,
                MemoryChunk.source_id,
                MemoryChunk.chunk_type,
                MemoryChunk.chunk_text.label("text"),
                MemoryChunk.summary_text,
                MemoryChunk.metadata_json,
                MemoryChunk.embedding_status,
                MemoryChunk.created_at,
                MemoryChunk.updated_at,
                source_ts_expr.label(SOURCE_TIMESTAMP_KEY),
                distance_expr,
            )
            .where(
                MemoryChunk.project_id == project_id,
                MemoryChunk.embedding.isnot(None),
            )
        )

        if only_done:
            stmt = stmt.where(MemoryChunk.embedding_status == "done")
        if exclude_forgetting_stages:
            stmt = stmt.where(
                forgetting_stage_expr.is_(None)
                | (~forgetting_stage_expr.in_(tuple(exclude_forgetting_stages)))
            )
        if source_type is not None:
            stmt = stmt.where(MemoryChunk.source_type == source_type)
        if chunk_type is not None:
            stmt = stmt.where(MemoryChunk.chunk_type == chunk_type)
        if max_distance is not None:
            stmt = stmt.where(distance_expr <= float(max_distance))
        if source_timestamp_gte is not None:
            normalized_gte = normalize_source_timestamp(source_timestamp_gte)
            stmt = stmt.where(
                source_ts_expr.isnot(None),
                source_ts_expr >= normalized_gte,
            )
        if source_timestamp_lte is not None:
            normalized_lte = normalize_source_timestamp(source_timestamp_lte)
            stmt = stmt.where(
                source_ts_expr.isnot(None),
                source_ts_expr <= normalized_lte,
            )

        if sort_by == "source_timestamp_desc":
            stmt = stmt.order_by(source_ts_expr.desc().nullslast(), distance_expr.asc())
        elif sort_by == "source_timestamp_asc":
            stmt = stmt.order_by(source_ts_expr.asc().nullslast(), distance_expr.asc())
        elif sort_by == "distance_then_source_timestamp_desc":
            stmt = stmt.order_by(distance_expr.asc(), source_ts_expr.desc().nullslast())
        else:
            stmt = stmt.order_by(distance_expr.asc())

        stmt = stmt.limit(top_k)

        result = self.db.execute(stmt)

        rows = []
        for row in result.mappings():
            rows.append(
                {
                    "id": row["id"],
                    "project_id": row["project_id"],
                    "source_type": row["source_type"],
                    "source_id": row["source_id"],
                    "chunk_type": row["chunk_type"],
                    "text": row["text"],
                    "summary_text": row["summary_text"],
                    "metadata_json": row["metadata_json"],
                    "embedding_status": row["embedding_status"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    SOURCE_TIMESTAMP_KEY: row[SOURCE_TIMESTAMP_KEY],
                    "distance": float(row["distance"]),
                }
            )

        return rows

    def keyword_search(
        self,
        project_id,
        query_text: str,
        top_k: int = 20,
        source_type: str | None = None,
        chunk_type: str | None = None,
        only_done: bool = True,
        exclude_forgetting_stages: tuple[str, ...] | None = (
            "suppressed",
            "archived",
            "deleted",
        ),
        source_timestamp_gte: str | datetime | None = None,
        source_timestamp_lte: str | datetime | None = None,
        sort_by: str = "keyword_score_desc",
    ) -> list[dict]:
        """
        关键词检索（PostgreSQL 全文检索）。

        说明：
        - 使用 `websearch_to_tsquery + to_tsvector + ts_rank_cd`。
        - 主要用于 hybrid search 的关键词召回分支。
        """
        if top_k <= 0:
            return []
        if not isinstance(query_text, str) or not query_text.strip():
            return []
        self._validate_keyword_sort(sort_by)

        source_ts_expr = MemoryChunk.metadata_json[SOURCE_TIMESTAMP_KEY].astext
        forgetting_stage_expr = MemoryChunk.metadata_json["forgetting_stage"].astext
        ts_query = func.websearch_to_tsquery(
            "simple",
            bindparam("query_text", value=query_text.strip()),
        )
        ts_vector = func.to_tsvector(
            "simple",
            func.concat_ws(
                " ",
                func.coalesce(MemoryChunk.summary_text, ""),
                func.coalesce(MemoryChunk.chunk_text, ""),
            ),
        )
        match_expr = ts_vector.op("@@")(ts_query)
        keyword_score_expr = func.ts_rank_cd(ts_vector, ts_query).label("keyword_score")

        stmt = (
            select(
                MemoryChunk.id,
                MemoryChunk.project_id,
                MemoryChunk.source_type,
                MemoryChunk.source_id,
                MemoryChunk.chunk_type,
                MemoryChunk.chunk_text.label("text"),
                MemoryChunk.summary_text,
                MemoryChunk.metadata_json,
                MemoryChunk.embedding_status,
                MemoryChunk.created_at,
                MemoryChunk.updated_at,
                source_ts_expr.label(SOURCE_TIMESTAMP_KEY),
                keyword_score_expr,
            )
            .where(
                MemoryChunk.project_id == project_id,
                MemoryChunk.chunk_text.isnot(None),
                match_expr,
            )
        )

        if only_done:
            stmt = stmt.where(MemoryChunk.embedding_status == "done")
        if exclude_forgetting_stages:
            stmt = stmt.where(
                forgetting_stage_expr.is_(None)
                | (~forgetting_stage_expr.in_(tuple(exclude_forgetting_stages)))
            )
        if source_type is not None:
            stmt = stmt.where(MemoryChunk.source_type == source_type)
        if chunk_type is not None:
            stmt = stmt.where(MemoryChunk.chunk_type == chunk_type)
        if source_timestamp_gte is not None:
            normalized_gte = normalize_source_timestamp(source_timestamp_gte)
            stmt = stmt.where(
                source_ts_expr.isnot(None),
                source_ts_expr >= normalized_gte,
            )
        if source_timestamp_lte is not None:
            normalized_lte = normalize_source_timestamp(source_timestamp_lte)
            stmt = stmt.where(
                source_ts_expr.isnot(None),
                source_ts_expr <= normalized_lte,
            )

        if sort_by == "source_timestamp_desc":
            stmt = stmt.order_by(source_ts_expr.desc().nullslast(), keyword_score_expr.desc())
        elif sort_by == "source_timestamp_asc":
            stmt = stmt.order_by(source_ts_expr.asc().nullslast(), keyword_score_expr.desc())
        else:
            stmt = stmt.order_by(keyword_score_expr.desc(), MemoryChunk.created_at.desc())

        stmt = stmt.limit(top_k)
        result = self.db.execute(stmt)

        rows = []
        for row in result.mappings():
            rows.append(
                {
                    "id": row["id"],
                    "project_id": row["project_id"],
                    "source_type": row["source_type"],
                    "source_id": row["source_id"],
                    "chunk_type": row["chunk_type"],
                    "text": row["text"],
                    "summary_text": row["summary_text"],
                    "metadata_json": row["metadata_json"],
                    "embedding_status": row["embedding_status"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    SOURCE_TIMESTAMP_KEY: row[SOURCE_TIMESTAMP_KEY],
                    "keyword_score": float(row["keyword_score"]),
                }
            )
        if rows:
            return rows

        # CJK fallback：PostgreSQL simple FTS 对中文分词能力有限。
        # 当 FTS 无命中时，回退到“子串匹配 + 计分”以保证中文问法可召回。
        if self._contains_cjk(query_text):
            return self._keyword_search_cjk_fallback(
                project_id=project_id,
                query_text=query_text,
                top_k=top_k,
                source_type=source_type,
                chunk_type=chunk_type,
                only_done=only_done,
                exclude_forgetting_stages=exclude_forgetting_stages,
                source_timestamp_gte=source_timestamp_gte,
                source_timestamp_lte=source_timestamp_lte,
                sort_by=sort_by,
            )
        return []

    def _set_embedding_state(
        self,
        chunk_id,
        status: str,
        *,
        embedding: list[float] | None = None,
        auto_commit: bool = True,
    ) -> MemoryChunk | None:
        self._validate_embedding_status(status)

        chunk = self.get(chunk_id)
        if not chunk:
            return None

        current_status = str(chunk.embedding_status)
        if current_status != status:
            allowed = self._ALLOWED_EMBEDDING_TRANSITIONS.get(current_status, set())
            if status not in allowed:
                allowed_text = ", ".join(sorted(allowed)) if allowed else "(无)"
                raise ValueError(
                    "embedding_status 非法流转："
                    f"{current_status} -> {status}，允许: {allowed_text}"
                )

        if embedding is not None:
            self._validate_embedding(embedding)
            chunk.embedding = embedding

        chunk.embedding_status = status
        if auto_commit:
            self.db.commit()
            self.db.refresh(chunk)
        else:
            self.db.flush()
        return chunk

    def _validate_embedding(self, embedding: list[float]) -> None:
        if len(embedding) != self._EMBEDDING_DIM:
            raise ValueError(
                f"embedding 维度错误：期望 {self._EMBEDDING_DIM}，实际 {len(embedding)}"
            )

    def _validate_embedding_status(self, status: str) -> None:
        if status not in self._ALLOWED_EMBEDDING_STATUS:
            allowed = ", ".join(sorted(self._ALLOWED_EMBEDDING_STATUS))
            raise ValueError(f"embedding_status 非法: {status}，允许值: {allowed}")

    def _validate_list_sort(self, sort_by: str) -> None:
        if sort_by not in self._ALLOWED_LIST_SORT:
            allowed = ", ".join(sorted(self._ALLOWED_LIST_SORT))
            raise ValueError(f"list sort 非法: {sort_by}，允许值: {allowed}")

    def _validate_similarity_sort(self, sort_by: str) -> None:
        if sort_by not in self._ALLOWED_SIMILARITY_SORT:
            allowed = ", ".join(sorted(self._ALLOWED_SIMILARITY_SORT))
            raise ValueError(f"similarity sort 非法: {sort_by}，允许值: {allowed}")

    def _validate_keyword_sort(self, sort_by: str) -> None:
        if sort_by not in self._ALLOWED_KEYWORD_SORT:
            allowed = ", ".join(sorted(self._ALLOWED_KEYWORD_SORT))
            raise ValueError(f"keyword sort 非法: {sort_by}，允许值: {allowed}")

    def _keyword_search_cjk_fallback(
        self,
        *,
        project_id,
        query_text: str,
        top_k: int,
        source_type: str | None,
        chunk_type: str | None,
        only_done: bool,
        exclude_forgetting_stages: tuple[str, ...] | None,
        source_timestamp_gte: str | datetime | None,
        source_timestamp_lte: str | datetime | None,
        sort_by: str,
    ) -> list[dict]:
        terms = self._extract_cjk_terms(query_text)
        if not terms:
            return []

        source_ts_expr = MemoryChunk.metadata_json[SOURCE_TIMESTAMP_KEY].astext
        forgetting_stage_expr = MemoryChunk.metadata_json["forgetting_stage"].astext
        chunk_text_expr = func.coalesce(MemoryChunk.chunk_text, "")

        score_expr = None
        for idx, term in enumerate(terms):
            cond = func.strpos(chunk_text_expr, bindparam(f"cjk_term_{idx}", value=term)) > 0
            part = case((cond, 1), else_=0)
            score_expr = part if score_expr is None else score_expr + part

        if score_expr is None:
            return []
        keyword_score_expr = score_expr.label("keyword_score")

        stmt = (
            select(
                MemoryChunk.id,
                MemoryChunk.project_id,
                MemoryChunk.source_type,
                MemoryChunk.source_id,
                MemoryChunk.chunk_type,
                MemoryChunk.chunk_text.label("text"),
                MemoryChunk.metadata_json,
                MemoryChunk.embedding_status,
                MemoryChunk.created_at,
                MemoryChunk.updated_at,
                source_ts_expr.label(SOURCE_TIMESTAMP_KEY),
                keyword_score_expr,
            )
            .where(
                MemoryChunk.project_id == project_id,
                MemoryChunk.chunk_text.isnot(None),
                keyword_score_expr > 0,
            )
        )

        if only_done:
            stmt = stmt.where(MemoryChunk.embedding_status == "done")
        if exclude_forgetting_stages:
            stmt = stmt.where(
                forgetting_stage_expr.is_(None)
                | (~forgetting_stage_expr.in_(tuple(exclude_forgetting_stages)))
            )
        if source_type is not None:
            stmt = stmt.where(MemoryChunk.source_type == source_type)
        if chunk_type is not None:
            stmt = stmt.where(MemoryChunk.chunk_type == chunk_type)
        if source_timestamp_gte is not None:
            normalized_gte = normalize_source_timestamp(source_timestamp_gte)
            stmt = stmt.where(
                source_ts_expr.isnot(None),
                source_ts_expr >= normalized_gte,
            )
        if source_timestamp_lte is not None:
            normalized_lte = normalize_source_timestamp(source_timestamp_lte)
            stmt = stmt.where(
                source_ts_expr.isnot(None),
                source_ts_expr <= normalized_lte,
            )

        if sort_by == "source_timestamp_desc":
            stmt = stmt.order_by(source_ts_expr.desc().nullslast(), keyword_score_expr.desc())
        elif sort_by == "source_timestamp_asc":
            stmt = stmt.order_by(source_ts_expr.asc().nullslast(), keyword_score_expr.desc())
        else:
            stmt = stmt.order_by(keyword_score_expr.desc(), MemoryChunk.created_at.desc())

        stmt = stmt.limit(top_k)
        result = self.db.execute(stmt)

        rows = []
        for row in result.mappings():
            rows.append(
                {
                    "id": row["id"],
                    "project_id": row["project_id"],
                    "source_type": row["source_type"],
                    "source_id": row["source_id"],
                    "chunk_type": row["chunk_type"],
                    "text": row["text"],
                    "metadata_json": row["metadata_json"],
                    "embedding_status": row["embedding_status"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    SOURCE_TIMESTAMP_KEY: row[SOURCE_TIMESTAMP_KEY],
                    "keyword_score": float(row["keyword_score"]),
                }
            )
        return rows

    @classmethod
    def _contains_cjk(cls, text: str) -> bool:
        return bool(cls._CJK_SEQ_RE.search(text or ""))

    @classmethod
    def _extract_cjk_terms(cls, text: str) -> list[str]:
        terms: list[str] = []
        seen: set[str] = set()
        for seq in cls._CJK_SEQ_RE.findall(text or ""):
            seq = seq.strip()
            if len(seq) < 2:
                continue
            # 保留原序列
            candidates = [seq]
            # 追加 2-gram，提升中文子串匹配召回稳定性
            candidates.extend(seq[i : i + 2] for i in range(0, len(seq) - 1))
            for term in candidates:
                if len(term) < 2:
                    continue
                if term in cls._CJK_NOISE_TERMS:
                    continue
                if term in seen:
                    continue
                seen.add(term)
                terms.append(term)
                if len(terms) >= 16:
                    return terms
        return terms

    @staticmethod
    def _normalize_metadata_json(metadata_json: dict | None) -> dict:
        if metadata_json is None:
            return {}
        if not isinstance(metadata_json, dict):
            raise ValueError("metadata_json 必须是 dict 或 None")

        normalized = dict(metadata_json)
        if SOURCE_TIMESTAMP_KEY in normalized:
            normalized[SOURCE_TIMESTAMP_KEY] = normalize_source_timestamp(
                normalized[SOURCE_TIMESTAMP_KEY]
            )
        return normalized
