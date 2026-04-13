# Retrieval Release Checklist

Last updated: 2026-04-07 (Asia/Shanghai)

## 1. Schema & Migration
- [x] `alembic upgrade head` 已在本地环境执行（`f2c3d4e5f6a7`）
- [x] `embedding_status_enum` 扩展态可读写（queued/retrying/stale）
- [x] 新增在线评测与生命周期持久化表已创建
  - `retrieval_eval_events`
  - `retrieval_eval_daily_stats`
  - `embedding_job_runs`
  - `memory_rebuild_checkpoints`

## 2. Quality Baseline
- [x] `scripts/test_memory_ingestion_service.py` 通过
- [x] `scripts/test_memory_dedup_pipeline.py` 通过
- [x] `scripts/test_memory_search_service.py` 通过
- [x] pipeline 契约测试通过（`scripts/test_retrieval_pipeline_contract.py`）
- [x] 单元测试通过（`tests/unit/test_*.py`）

## 3. Runtime Metrics
- [x] 已落地结构化指标采集点（search/ingestion/fallback/rerank）
- [x] 已落地本地门禁阈值检查脚本（`scripts/release_gate.py`）
- [ ] 线上空结果率低于阈值（需注入 `WRITER_METRIC_EMPTY_RESULT_RATE`）
- [ ] 线上 fallback 命中率在预期区间（需注入 `WRITER_METRIC_FALLBACK_HIT_RATE`）
- [ ] 线上 embedding 失败率低于阈值（需注入 `WRITER_METRIC_EMBEDDING_FAILURE_RATE`）
- [ ] 线上检索 P95 延迟在 SLA 内（需注入 `WRITER_METRIC_RETRIEVAL_P95_MS`）

## 4. Rollback & Recovery
- [x] 失败重试入口可用（failed -> pending）
- [x] 卡住 processing 恢复入口可用
- [x] stale 重算流程可执行
- [x] rebuild checkpoint 持久化可断点续跑

## 5. Release Gate Commands
- [x] `./venv/bin/python scripts/release_gate.py --allow-missing-metrics`
- [x] `./venv/bin/python scripts/release_gate.py --skip-integration --allow-missing-metrics`

## 6. Optional Backends
- [x] vector backend 选择配置已接入
  - `WRITER_RETRIEVAL_VECTOR_BACKEND=pgvector|faiss|milvus|qdrant`
- [x] rerank backend 选择配置已接入
  - `WRITER_RETRIEVAL_RERANK_BACKEND=rule|cross_encoder`
- [x] cross-encoder 外部服务配置已接入
  - `WRITER_RERANK_SERVICE_BASE_URL`
  - `WRITER_RERANK_SERVICE_API_KEY`
  - `WRITER_RERANK_SERVICE_MODEL`
  - `WRITER_RERANK_SERVICE_TIMEOUT`
