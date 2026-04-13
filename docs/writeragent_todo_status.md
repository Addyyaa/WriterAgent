# WriterAgent TODO Status (Implemented)

Last verified: 2026-04-07 (Asia/Shanghai)

## P0 Long-Term Memory Stabilization
- [x] `P0-1` 主链参数配置化
  - `packages/memory/long_term/runtime_config.py`
  - `packages/retrieval/config.py`
- [x] `P0-2` 主链可观测性（结构化日志 + 指标）
  - `packages/memory/long_term/observability.py`
  - `packages/memory/long_term/ingestion/ingestion_service.py`
  - `packages/memory/long_term/search/search_service.py`
- [x] `P0-3` 主链一致性加固（重试 + 异常恢复）
  - `packages/memory/long_term/ingestion/ingestion_service.py`
  - `packages/storage/postgres/repositories/memory_repository.py`
- [x] `P0-4` 基线测试固化（高样本、隔离、时间排序、无命中）
  - `scripts/test_memory_search_service.py`
  - `scripts/test_memory_ingestion_service.py`
  - `scripts/test_memory_dedup_pipeline.py`

## P1 Retrieval Platformization
- [x] `P1-1` Retrieval 核心类型与错误模型
  - `packages/retrieval/types.py`
  - `packages/retrieval/errors.py`
- [x] `P1-2` Pipeline 主干
  - `packages/retrieval/pipeline.py`
- [x] `P1-3` 融合与重排抽象
  - `packages/retrieval/hybrid/*`
  - `packages/retrieval/rerank/*`
- [x] `P1-4` Memory 适配迁移（保留 API）
  - `packages/memory/long_term/search/search_service.py`
- [x] `P1-5` 多向量后端完整实现（pgvector/faiss/milvus/qdrant）
  - `packages/retrieval/vector/*`
  - `packages/retrieval/vector/factory.py`

## P2 Multi-Layer Memory
- [x] `P2-1` Short-term memory
  - `packages/memory/short_term/session_memory.py`
- [x] `P2-2` Working memory
  - `packages/memory/working_memory/context_builder.py`
- [x] `P2-3` Project memory
  - `packages/memory/project_memory/project_memory_service.py`

## P3 Lifecycle Automation
- [x] `P3-1` Embedding 作业 runner（run_once + run_loop + 持久化）
  - `packages/memory/long_term/lifecycle/embedding_jobs.py`
  - `packages/storage/postgres/repositories/embedding_job_run_repository.py`
  - `packages/storage/postgres/models/embedding_job_run.py`
- [x] `P3-2` Rebuild / stale / checkpoint（持久化断点）
  - `packages/memory/long_term/lifecycle/rebuild.py`
  - `packages/storage/postgres/repositories/memory_rebuild_checkpoint_repository.py`
  - `packages/storage/postgres/models/memory_rebuild_checkpoint.py`
- [x] `P3-3` 状态扩展与迁移
  - `packages/storage/postgres/models/memory_chunk.py`
  - `packages/storage/postgres/repositories/memory_repository.py`
  - `migrations/versions/e8f1b2c3d4a5_expand_embedding_status_enum.py`

## P4 Evaluation and Release Gate
- [x] `P4-1` 离线评测（Recall@K/MRR/nDCG）
  - `packages/retrieval/evaluators/offline_eval.py`
  - `packages/retrieval/evaluators/metrics.py`
- [x] `P4-2` 在线评测落库（事件 + 日聚合 + A/B）
  - `packages/storage/postgres/models/retrieval_eval_event.py`
  - `packages/storage/postgres/models/retrieval_eval_daily_stat.py`
  - `packages/storage/postgres/repositories/retrieval_eval_repository.py`
  - `packages/retrieval/evaluators/online_eval_service.py`
  - `packages/memory/long_term/search/search_service.py`
- [x] `P4-3` 发布门禁本地自动化
  - `scripts/release_gate.py`
  - `docs/retrieval_release_checklist.md`

## Schema / Migration
- [x] 新增迁移
  - `migrations/versions/f2c3d4e5f6a7_add_retrieval_eval_and_lifecycle_tables.py`

## Dependencies
- [x] 主链依赖文件
  - `requirements.txt`
- [x] 可选依赖文件
  - `requirements-optional.txt`

## Required Public Interfaces
- [x] `RetrievalPipeline.run(query, filters, options) -> list[ScoredDoc]`
- [x] `ProjectMemoryService.build_context(project_id, query, token_budget)`
- [x] `EmbeddingJobRunner.run_once(limit, batch_size)`
- [x] `MemorySearchService.search_texts/search_with_scores` compatibility kept
- [x] `MemorySearchService.record_feedback(project_id, request_id, user_id, clicked_doc_id, clicked=True)`

## Validation (Local)
- [x] `./venv/bin/alembic upgrade head`
- [x] `./venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py' -v`
- [x] `./venv/bin/python scripts/test_retrieval_pipeline_contract.py`
- [x] `./venv/bin/python scripts/test_memory_ingestion_service.py`
- [x] `./venv/bin/python scripts/test_memory_dedup_pipeline.py`
- [x] `./venv/bin/python scripts/test_memory_search_service.py`
- [x] `./venv/bin/python scripts/release_gate.py --allow-missing-metrics`
