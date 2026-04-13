"""
双存储严格评测脚本（升级版）：
1) 业务表直读检索（chapters + BM25）
2) 向量检索（memory_chunks）
   - vector_only: 仅向量，不启用 hybrid/rerank
   - vector_hybrid: 启用 hybrid + rerank（默认）

同时输出：
- chapter 级指标（命中章节）
- chunk 级指标（命中证据片段）

运行：
    python3 scripts/test_dual_storage_retrieval_demo.py

可选环境变量：
    DATABASE_URL=postgresql+psycopg2://addy:sf123123@localhost:5432/writer_agent_db
    DEMO_TOP_K=8
    DEMO_NOISE_SIZE=120
    DEMO_VERBOSE=1
    DEMO_EMBEDDING_MODE=real|deterministic|both   (默认 real)
    DEMO_VECTOR_ENABLE_HYBRID=1
    DEMO_VECTOR_ENABLE_RERANK=1
    DEMO_VECTOR_MAX_DISTANCE=   (默认空，表示不设阈值)
"""

from __future__ import annotations

import os
import random
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import sessionmaker

_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from packages.llm.embeddings.factory import create_embedding_provider_from_env
from packages.memory.long_term.ingestion.ingestion_service import MemoryIngestionService
from packages.memory.long_term.search.search_service import MemorySearchService
from packages.retrieval.chunking.simple_text_chunker import SimpleTextChunker
from packages.retrieval.evaluators.metrics import mrr
from packages.retrieval.keyword.bm25_retriever import BM25Retriever
from packages.storage.postgres.repositories.chapter_repository import ChapterRepository
from packages.storage.postgres.repositories.memory_fact_repository import (
    MemoryFactRepository,
)
from packages.storage.postgres.repositories.memory_repository import MemoryChunkRepository
from packages.storage.postgres.repositories.project_repository import ProjectRepository
from scripts._chapter_workflow_support import DeterministicEmbeddingProvider
from scripts._db_engine import create_engine_with_driver_fallback

_DEFAULT_DATABASE_URL = "postgresql+psycopg2://addy:sf123123@localhost:5432/writer_agent_db"


@dataclass(frozen=True)
class QueryCase:
    name: str
    query: str
    relevant_chapter_nos: set[int]


def main() -> None:
    db_url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
    top_k = max(1, int(os.environ.get("DEMO_TOP_K", "8")))
    noise_size = max(0, int(os.environ.get("DEMO_NOISE_SIZE", "120")))
    verbose = _env_bool("DEMO_VERBOSE", True)
    embedding_mode = os.environ.get("DEMO_EMBEDDING_MODE", "real").strip().lower()
    vector_enable_hybrid = _env_bool("DEMO_VECTOR_ENABLE_HYBRID", True)
    vector_enable_rerank = _env_bool("DEMO_VECTOR_ENABLE_RERANK", True)
    vector_max_distance = _env_float_or_none("DEMO_VECTOR_MAX_DISTANCE")

    engine = create_engine_with_driver_fallback(db_url, echo=False)
    session_local = sessionmaker(bind=engine)
    db = session_local()
    try:
        if embedding_mode == "both":
            _run_single_mode(
                db=db,
                mode="deterministic",
                top_k=top_k,
                noise_size=noise_size,
                verbose=verbose,
                vector_enable_hybrid=vector_enable_hybrid,
                vector_enable_rerank=vector_enable_rerank,
                vector_max_distance=vector_max_distance,
            )
            print("\n")
            _run_single_mode(
                db=db,
                mode="real",
                top_k=top_k,
                noise_size=noise_size,
                verbose=verbose,
                vector_enable_hybrid=vector_enable_hybrid,
                vector_enable_rerank=vector_enable_rerank,
                vector_max_distance=vector_max_distance,
            )
            return
        _run_single_mode(
            db=db,
            mode=("real" if embedding_mode not in {"real", "deterministic"} else embedding_mode),
            top_k=top_k,
            noise_size=noise_size,
            verbose=verbose,
            vector_enable_hybrid=vector_enable_hybrid,
            vector_enable_rerank=vector_enable_rerank,
            vector_max_distance=vector_max_distance,
        )
    finally:
        db.close()


def _run_single_mode(
    *,
    db,
    mode: str,
    top_k: int,
    noise_size: int,
    verbose: bool,
    vector_enable_hybrid: bool,
    vector_enable_rerank: bool,
    vector_max_distance: float | None,
) -> None:
    project_repo = ProjectRepository(db)
    chapter_repo = ChapterRepository(db)
    memory_repo = MemoryChunkRepository(db)
    memory_fact_repo = MemoryFactRepository(db)

    provider_name = mode
    if mode == "deterministic":
        embedding_provider = DeterministicEmbeddingProvider()
    else:
        try:
            embedding_provider = create_embedding_provider_from_env()
            provider_name = type(embedding_provider).__name__
        except Exception as exc:
            raise RuntimeError(
                "真实 embedding provider 初始化失败。请检查 WRITER_EMBEDDING_PROVIDER / EMBEDDING_* 环境变量。"
            ) from exc

    ingestion_service = MemoryIngestionService(
        chunker=SimpleTextChunker(chunk_size=220, chunk_overlap=50),
        embedding_provider=embedding_provider,
        memory_repo=memory_repo,
        memory_fact_repo=memory_fact_repo,
        embedding_batch_size=8,
        replace_existing_by_default=True,
        enable_semantic_dedup=False,
    )
    search_service = MemorySearchService(
        embedding_provider=embedding_provider,
        memory_repo=memory_repo,
    )

    project = project_repo.create(
        title=f"双存储严格评测-{mode}",
        genre="悬疑",
        premise="比较业务检索与向量检索在干扰语料下的效果",
    )

    targets = _build_target_corpus()
    noise = _build_noise_corpus(start_chapter_no=4, size=noise_size)
    all_chapters = list(targets) + list(noise)

    chapter_no_by_source_id: dict[str, int] = {}
    chunk_ids_by_chapter_no: dict[int, set[str]] = {}
    chunk_id_to_chapter_no: dict[str, int] = {}

    for chapter_no, content in all_chapters:
        chapter, _, _ = chapter_repo.save_generated_draft(
            project_id=project.id,
            chapter_no=chapter_no,
            title=f"第{chapter_no}章",
            content=content,
            summary=content[:80],
            source_agent="demo_script",
            source_workflow=f"strict_eval_{mode}",
            trace_id=f"strict-{mode}",
        )
        chapter_id = str(chapter.id)
        chapter_no_by_source_id[chapter_id] = int(chapter_no)
        inserted_chunks = ingestion_service.ingest_text(
            project_id=project.id,
            text=content,
            source_type="chapter",
            source_id=chapter.id,
            chunk_type="chapter_body",
            metadata_json={"chapter_no": chapter_no, "demo_mode": mode},
            source_timestamp=datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            replace_existing=True,
        )
        for chunk in inserted_chunks:
            chunk_id = str(chunk.id)
            chunk_id_to_chapter_no[chunk_id] = int(chapter_no)
            chunk_ids_by_chapter_no.setdefault(int(chapter_no), set()).add(chunk_id)

    queries = _build_query_set()
    business_scores_chapter: list[dict[str, float]] = []
    vector_only_scores_chapter: list[dict[str, float]] = []
    vector_hybrid_scores_chapter: list[dict[str, float]] = []
    vector_only_scores_chunk: list[dict[str, float]] = []
    vector_hybrid_scores_chunk: list[dict[str, float]] = []

    print("=" * 120)
    print("Strict Dual-Storage Eval (BM25 baseline + vector pipeline)")
    print(f"mode={mode} provider={provider_name}")
    print(f"project_id={project.id}")
    print(
        f"top_k={top_k}, total_docs={len(all_chapters)}, positives={len(targets)}, noise={len(noise)}, "
        f"vector_hybrid={vector_enable_hybrid}, vector_rerank={vector_enable_rerank}, "
        f"vector_max_distance={vector_max_distance}"
    )
    print("=" * 120)

    for case in queries:
        relevant_chunk_ids = _build_relevant_chunk_ids(
            relevant_chapter_nos=case.relevant_chapter_nos,
            chunk_ids_by_chapter_no=chunk_ids_by_chapter_no,
        )

        business_rows = _business_table_retrieve_bm25(
            chapter_repo=chapter_repo,
            project_id=project.id,
            query=case.query,
            top_k=top_k,
        )
        vector_only_rows = _vector_retrieve(
            search_service=search_service,
            project_id=project.id,
            query=case.query,
            top_k=top_k,
            enable_hybrid=False,
            enable_rerank=False,
            max_distance=vector_max_distance,
        )
        vector_hybrid_rows = _vector_retrieve(
            search_service=search_service,
            project_id=project.id,
            query=case.query,
            top_k=top_k,
            enable_hybrid=vector_enable_hybrid,
            enable_rerank=vector_enable_rerank,
            max_distance=vector_max_distance,
        )

        b_hits_chapter = _hits_for_business_chapter(
            rows=business_rows,
            relevant_chapter_nos=case.relevant_chapter_nos,
            top_k=top_k,
        )
        vo_hits_chapter = _hits_for_vector_chapter(
            rows=vector_only_rows,
            chunk_id_to_chapter_no=chunk_id_to_chapter_no,
            chapter_no_by_source_id=chapter_no_by_source_id,
            relevant_chapter_nos=case.relevant_chapter_nos,
            top_k=top_k,
        )
        vh_hits_chapter = _hits_for_vector_chapter(
            rows=vector_hybrid_rows,
            chunk_id_to_chapter_no=chunk_id_to_chapter_no,
            chapter_no_by_source_id=chapter_no_by_source_id,
            relevant_chapter_nos=case.relevant_chapter_nos,
            top_k=top_k,
        )
        vo_hits_chunk = _hits_for_vector_chunk(
            rows=vector_only_rows,
            relevant_chunk_ids=relevant_chunk_ids,
            top_k=top_k,
        )
        vh_hits_chunk = _hits_for_vector_chunk(
            rows=vector_hybrid_rows,
            relevant_chunk_ids=relevant_chunk_ids,
            top_k=top_k,
        )

        b_metric_chapter = _metrics_from_hits(
            b_hits_chapter,
            top_k=top_k,
            relevant_total=max(1, len(case.relevant_chapter_nos)),
        )
        vo_metric_chapter = _metrics_from_hits(
            vo_hits_chapter,
            top_k=top_k,
            relevant_total=max(1, len(case.relevant_chapter_nos)),
        )
        vh_metric_chapter = _metrics_from_hits(
            vh_hits_chapter,
            top_k=top_k,
            relevant_total=max(1, len(case.relevant_chapter_nos)),
        )
        vo_metric_chunk = _metrics_from_hits(
            vo_hits_chunk,
            top_k=top_k,
            relevant_total=max(1, len(relevant_chunk_ids)),
        )
        vh_metric_chunk = _metrics_from_hits(
            vh_hits_chunk,
            top_k=top_k,
            relevant_total=max(1, len(relevant_chunk_ids)),
        )

        business_scores_chapter.append(b_metric_chapter)
        vector_only_scores_chapter.append(vo_metric_chapter)
        vector_hybrid_scores_chapter.append(vh_metric_chapter)
        vector_only_scores_chunk.append(vo_metric_chunk)
        vector_hybrid_scores_chunk.append(vh_metric_chunk)

        print(f"[Query] {case.name}: {case.query}")
        print(f"  relevant_chapters={sorted(case.relevant_chapter_nos)}")
        print(
            f"  business(chapter)     -> Hit@{top_k}={b_metric_chapter['hit_at_k']:.3f}, "
            f"Precision@{top_k}={b_metric_chapter['precision_at_k']:.3f}, "
            f"MRR@{top_k}={b_metric_chapter['mrr_at_k']:.3f}, "
            f"Recall@{top_k}={b_metric_chapter['recall_at_k']:.3f}"
        )
        print(
            f"  vector_only(chapter)  -> Hit@{top_k}={vo_metric_chapter['hit_at_k']:.3f}, "
            f"Precision@{top_k}={vo_metric_chapter['precision_at_k']:.3f}, "
            f"MRR@{top_k}={vo_metric_chapter['mrr_at_k']:.3f}, "
            f"Recall@{top_k}={vo_metric_chapter['recall_at_k']:.3f}"
        )
        print(
            f"  vector_hybrid(chapter)-> Hit@{top_k}={vh_metric_chapter['hit_at_k']:.3f}, "
            f"Precision@{top_k}={vh_metric_chapter['precision_at_k']:.3f}, "
            f"MRR@{top_k}={vh_metric_chapter['mrr_at_k']:.3f}, "
            f"Recall@{top_k}={vh_metric_chapter['recall_at_k']:.3f}"
        )
        print(
            f"  vector_only(chunk)    -> Hit@{top_k}={vo_metric_chunk['hit_at_k']:.3f}, "
            f"Precision@{top_k}={vo_metric_chunk['precision_at_k']:.3f}, "
            f"MRR@{top_k}={vo_metric_chunk['mrr_at_k']:.3f}, "
            f"Recall@{top_k}={vo_metric_chunk['recall_at_k']:.3f}"
        )
        print(
            f"  vector_hybrid(chunk)  -> Hit@{top_k}={vh_metric_chunk['hit_at_k']:.3f}, "
            f"Precision@{top_k}={vh_metric_chunk['precision_at_k']:.3f}, "
            f"MRR@{top_k}={vh_metric_chunk['mrr_at_k']:.3f}, "
            f"Recall@{top_k}={vh_metric_chunk['recall_at_k']:.3f}"
        )

        if verbose:
            print("  business top:")
            for idx, row in enumerate(business_rows[:top_k], start=1):
                chapter_no = int(row["chapter_no"])
                flag = "HIT" if chapter_no in case.relevant_chapter_nos else "MISS"
                print(
                    f"    {idx}. [{flag}] ch={chapter_no} bm25={_fmt(row.get('keyword_score'))} "
                    f"title={row.get('title')}"
                )
            print("  vector_only top:")
            _print_vector_rows(
                rows=vector_only_rows,
                relevant_chapter_nos=case.relevant_chapter_nos,
                relevant_chunk_ids=relevant_chunk_ids,
                chunk_id_to_chapter_no=chunk_id_to_chapter_no,
                chapter_no_by_source_id=chapter_no_by_source_id,
                top_k=top_k,
            )
            print("  vector_hybrid top:")
            _print_vector_rows(
                rows=vector_hybrid_rows,
                relevant_chapter_nos=case.relevant_chapter_nos,
                relevant_chunk_ids=relevant_chunk_ids,
                chunk_id_to_chapter_no=chunk_id_to_chapter_no,
                chapter_no_by_source_id=chapter_no_by_source_id,
                top_k=top_k,
            )
        print("-" * 120)

    _print_macro_summary(label="business(chapter)", metrics=business_scores_chapter, top_k=top_k)
    _print_macro_summary(label="vector_only(chapter)", metrics=vector_only_scores_chapter, top_k=top_k)
    _print_macro_summary(label="vector_hybrid(chapter)", metrics=vector_hybrid_scores_chapter, top_k=top_k)
    _print_macro_summary(label="vector_only(chunk)", metrics=vector_only_scores_chunk, top_k=top_k)
    _print_macro_summary(label="vector_hybrid(chunk)", metrics=vector_hybrid_scores_chunk, top_k=top_k)
    print("=" * 120)


def _build_target_corpus() -> list[tuple[int, str]]:
    return [
        (
            1,
            "第1章：主角林澈在北港钟楼听见异常钟声，怀疑档案馆失火并非意外。"
            "他在雨夜追查守夜人，得到第一条线索。",
        ),
        (
            2,
            "第2章：林澈回到议事厅翻阅税单与港口记录，发现有人提前转移了易燃物。"
            "副官提醒他第七条协议曾被人篡改。",
        ),
        (
            3,
            "第3章：关键节点中，林澈在废弃钟楼地下室发现纵火装置，"
            "并确认守夜人与议会密探串联，决定公开证据。",
        ),
    ]


def _build_query_set() -> list[QueryCase]:
    return [
        QueryCase(name="Q1", query="主角在关键故事节点做了什么", relevant_chapter_nos={3}),
        QueryCase(name="Q2", query="主角在雨夜追查守夜人时得到了什么线索", relevant_chapter_nos={1}),
        QueryCase(name="Q3", query="第七条协议被篡改的线索来自哪里", relevant_chapter_nos={2}),
        QueryCase(name="Q4", query="纵火装置是在什么地方发现的", relevant_chapter_nos={3}),
        QueryCase(name="Q5", query="主角回到议事厅后调查了什么", relevant_chapter_nos={2}),
        QueryCase(name="Q6", query="档案馆失火并非意外这一判断最早出现在哪章", relevant_chapter_nos={1}),
        QueryCase(name="Q7", query="守夜人与谁串联并引发公开证据决策", relevant_chapter_nos={3}),
        QueryCase(name="Q8", query="易燃物提前转移的发现发生在哪章", relevant_chapter_nos={2}),
    ]


def _build_noise_corpus(*, start_chapter_no: int, size: int) -> list[tuple[int, str]]:
    random.seed(17)
    templates = [
        "第{n}章：港口税务记录整理，主角仅做日常盘点，与纵火案主线无直接推进。",
        "第{n}章：集市价格波动与粮仓维护会议纪要，主要讨论后勤与预算分配。",
        "第{n}章：修表匠访谈提到钟声偏差，但未涉及守夜人和议会密探线索。",
        "第{n}章：城防演练报告，描述巡逻路线调整，剧情冲突强度较低。",
        "第{n}章：旁支人物回忆童年，补充情感背景，不触发关键节点决策。",
        "第{n}章：航线测绘日志，讨论潮汐和锚地选择，与主角调查任务弱相关。",
        "第{n}章：传闻提及纵火装置但经核查为误报，调查被暂时中止。",
        "第{n}章：守夜人值班表更新，内容为节日轮岗，不涉及案情推进。",
        "第{n}章：议会公告讨论预算削减，与主角行动计划并不一致。",
    ]
    rows: list[tuple[int, str]] = []
    for i in range(size):
        chapter_no = start_chapter_no + i
        rows.append((chapter_no, random.choice(templates).format(n=chapter_no)))
    return rows


def _business_table_retrieve_bm25(
    *,
    chapter_repo: ChapterRepository,
    project_id,
    query: str,
    top_k: int,
) -> list[dict[str, Any]]:
    chapters = list(chapter_repo.list_by_project(project_id))
    if not chapters:
        return []
    corpus = [f"{row.title or ''}\n{row.summary or ''}\n{row.content or ''}" for row in chapters]
    retriever = BM25Retriever()
    retriever.index(corpus)
    hits = retriever.search(query, top_k=max(1, int(top_k)))
    rows: list[dict[str, Any]] = []
    for idx, score in hits:
        if idx < 0 or idx >= len(chapters):
            continue
        row = chapters[idx]
        rows.append(
            {
                "chapter_no": int(row.chapter_no),
                "title": row.title,
                "keyword_score": float(score),
                "content_preview": str(row.content or "")[:120],
            }
        )
    return rows


def _vector_retrieve(
    *,
    search_service: MemorySearchService,
    project_id,
    query: str,
    top_k: int,
    enable_hybrid: bool,
    enable_rerank: bool,
    max_distance: float | None,
) -> list[dict[str, Any]]:
    return search_service.search_with_scores(
        project_id=project_id,
        query=query,
        top_k=top_k,
        source_type="chapter",
        chunk_type="chapter_body",
        sort_by="relevance_then_recent",
        enable_hybrid=enable_hybrid,
        enable_rerank=enable_rerank,
        max_distance=max_distance,
        fallback_max_distance=None,
    )


def _build_relevant_chunk_ids(
    *,
    relevant_chapter_nos: set[int],
    chunk_ids_by_chapter_no: dict[int, set[str]],
) -> set[str]:
    out: set[str] = set()
    for chapter_no in relevant_chapter_nos:
        out.update(chunk_ids_by_chapter_no.get(int(chapter_no), set()))
    return out


def _hits_for_business_chapter(
    *,
    rows: list[dict[str, Any]],
    relevant_chapter_nos: set[int],
    top_k: int,
) -> list[int]:
    out = []
    for row in rows[:top_k]:
        out.append(1 if int(row["chapter_no"]) in relevant_chapter_nos else 0)
    while len(out) < top_k:
        out.append(0)
    return out


def _hits_for_vector_chapter(
    *,
    rows: list[dict[str, Any]],
    chunk_id_to_chapter_no: dict[str, int],
    chapter_no_by_source_id: dict[str, int],
    relevant_chapter_nos: set[int],
    top_k: int,
) -> list[int]:
    out: list[int] = []
    for row in rows[:top_k]:
        chapter_no = _resolve_chapter_no(
            row=row,
            chunk_id_to_chapter_no=chunk_id_to_chapter_no,
            chapter_no_by_source_id=chapter_no_by_source_id,
        )
        out.append(1 if chapter_no in relevant_chapter_nos else 0)
    while len(out) < top_k:
        out.append(0)
    return out


def _hits_for_vector_chunk(
    *,
    rows: list[dict[str, Any]],
    relevant_chunk_ids: set[str],
    top_k: int,
) -> list[int]:
    out: list[int] = []
    for row in rows[:top_k]:
        row_id = str(row.get("id") or "")
        out.append(1 if row_id and row_id in relevant_chunk_ids else 0)
    while len(out) < top_k:
        out.append(0)
    return out


def _resolve_chapter_no(
    *,
    row: dict[str, Any],
    chunk_id_to_chapter_no: dict[str, int],
    chapter_no_by_source_id: dict[str, int],
) -> int:
    row_id = str(row.get("id") or "")
    source_id = str(row.get("source_id") or "")
    if row_id and row_id in chunk_id_to_chapter_no:
        return int(chunk_id_to_chapter_no[row_id])
    if source_id and source_id in chapter_no_by_source_id:
        return int(chapter_no_by_source_id[source_id])
    return -1


def _metrics_from_hits(
    hits: list[int],
    *,
    top_k: int,
    relevant_total: int,
) -> dict[str, float]:
    bounded = hits[:top_k]
    hit = 1.0 if any(bounded) else 0.0
    precision = sum(bounded) / max(1, top_k)
    recall = sum(bounded) / max(1, relevant_total)
    return {
        "hit_at_k": hit,
        "precision_at_k": precision,
        "mrr_at_k": mrr(hits, k=top_k),
        "recall_at_k": min(1.0, recall),
    }


def _print_vector_rows(
    *,
    rows: list[dict[str, Any]],
    relevant_chapter_nos: set[int],
    relevant_chunk_ids: set[str],
    chunk_id_to_chapter_no: dict[str, int],
    chapter_no_by_source_id: dict[str, int],
    top_k: int,
) -> None:
    for idx, row in enumerate(rows[:top_k], start=1):
        chapter_no = _resolve_chapter_no(
            row=row,
            chunk_id_to_chapter_no=chunk_id_to_chapter_no,
            chapter_no_by_source_id=chapter_no_by_source_id,
        )
        row_id = str(row.get("id") or "")
        chapter_flag = "HIT" if chapter_no in relevant_chapter_nos else "MISS"
        chunk_flag = "HIT" if row_id in relevant_chunk_ids else "MISS"
        print(
            f"    {idx}. [chapter:{chapter_flag}|chunk:{chunk_flag}] "
            f"ch={chapter_no} id={row_id[:8]} "
            f"dist={_fmt(row.get('distance'))} "
            f"kw={_fmt(row.get('keyword_score'))} "
            f"hybrid={_fmt(row.get('hybrid_score'))} "
            f"rerank={_fmt(row.get('rerank_score'))} "
            f"text={str(row.get('text') or '')[:56]}"
        )


def _print_macro_summary(*, label: str, metrics: list[dict[str, float]], top_k: int) -> None:
    if not metrics:
        print(f"[macro:{label}] no data")
        return
    print(
        f"[macro:{label}] "
        f"Hit@{top_k}={statistics.mean(item['hit_at_k'] for item in metrics):.3f}, "
        f"Precision@{top_k}={statistics.mean(item['precision_at_k'] for item in metrics):.3f}, "
        f"MRR@{top_k}={statistics.mean(item['mrr_at_k'] for item in metrics):.3f}, "
        f"Recall@{top_k}={statistics.mean(item['recall_at_k'] for item in metrics):.3f}"
    )


def _fmt(value) -> str:
    if value is None:
        return "None"
    try:
        return f"{float(value):.4f}"
    except Exception:
        return str(value)


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float_or_none(name: str) -> float | None:
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    return float(value)


if __name__ == "__main__":
    main()

