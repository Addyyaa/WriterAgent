# WriterAgent

WriterAgent 是一个面向长篇小说写作的后端系统，当前已升级为“8 角色编排 + 动态规划器 + 检索驱动循环（最多 20 轮）+ 在线评测闭环 + schema/skills 强约束运行时”的可上线版本。

核心目标：
- 把写作流程做成可追踪、可回放、可运维的生产链路。
- 支持 `大纲 -> 章节 -> 一致性审查 -> 修订` 自动执行。
- 支持 LLM 按需检索（证据覆盖达标即停、连续低增益停机、20 轮封顶）。
- 统一长期记忆（摄入、去重、检索、遗忘、重建）与写作 workflow。

---

## 1. 系统架构（设计视角）

### 1.1 分层架构

```mermaid
flowchart TB
    C[Client] --> API[apps/api/main.py FastAPI v2]

    API --> ORCH[WritingOrchestratorService]
    ORCH --> PLAN[DynamicPlanner]
    ORCH --> RLOOP[RetrievalLoopService]
    ORCH --> REG[AgentRegistry]
    ORCH --> SCHEMA[SchemaRegistry]
    ORCH --> SKILL[SkillRegistry]

    PLAN --> DAG[Planner DAG]
    DAG --> OUTLINE[outline_generation]
    DAG --> CHAPTER[chapter_generation]
    DAG --> REVIEW[consistency_review]
    DAG --> REVISION[revision]

    RLOOP --> PM[ProjectMemoryService]
    RLOOP --> RTR[(retrieval_rounds/retrieval_evidence_items)]

    CHAPTER --> PM[ProjectMemoryService]
    PM --> STM[Short-Term Memory session_memory]
    PM --> WM[Working Memory context_builder]
    PM --> LTMR[Long-Term Memory Retrieval]
    LTMR --> SEARCH[MemorySearchService]
    SEARCH --> RET[RetrievalPipeline]
    RET --> VECTOR[Vector Store]
    RET --> KEYWORD[Keyword Retriever]

    CHAPTER --> INGEST[MemoryIngestionService]
    REVISION --> INGEST
    INGEST --> LTM[(Long-Term Memory Store)]
    LTM --> DB[(PostgreSQL + pgvector)]

    ORCH --> EVAL[OnlineEvaluationService]
    EVAL --> EDB[(evaluation_runs/events/daily)]

    WORKER[apps/orchestrator/worker.py] --> ORCH
    LIFE[scripts/run_lifecycle_scheduler.py] --> INGEST
    LIFE --> FORGET[MemoryForgettingService]
    LIFE --> REBUILD[MemoryRebuildService]
    FORGET --> LTM
    REBUILD --> LTM
```

### 1.1.1 架构图节点详细说明

1. `Client`：调用方（前端、脚本、其他服务），负责发起写作任务和查询任务。
2. `apps/api/main.py FastAPI v2`：HTTP 入口层，负责参数校验、依赖装配、错误映射与返回统一响应（v1 兼容接口默认关闭）。
3. `WritingOrchestratorService`：系统总调度器，负责创建 run、领取待执行任务、推进状态机、汇总结果与失败重试。
4. `DynamicPlanner`：规划器，负责把写作目标拆成可执行 DAG（步骤、依赖、回退策略）。
5. `AgentRegistry`：角色注册中心，动态加载 `apps/agents/*` 的 `prompt/strategy/schema/skills`。
6. `SchemaRegistry`：Schema 注册中心，统一做输入输出结构校验与 strict/degrade 模式控制。
7. `SkillRegistry`：技能注册中心，加载 `packages/skills/*/manifest.json` 并绑定到角色执行链路。
8. `Planner DAG`：规划结果数据结构，描述主流程步骤和依赖关系，是执行阶段的“任务蓝图”。
9. `outline_generation`：大纲工作流，产出项目级结构化大纲并版本化存储。
10. `chapter_generation`：章节生成工作流，按上下文和记忆生成章节内容并入库版本。
11. `consistency_review`：一致性审查工作流，检查角色设定、世界观、时间线和伏笔冲突。
12. `revision`：修订工作流，基于审查报告回写新版本章节。
13. `ProjectMemoryService`：记忆聚合门面，统一组装短期、工作、长期记忆上下文供写作使用。
14. `Short-Term Memory session_memory`：短期会话记忆，存放近期对话压缩/摘要，强调“最近性”。
15. `Working Memory context_builder`：工作记忆，按 token 预算与任务目标组装上下文，并在入模前做置信度门槛过滤（降低噪声证据干扰）。
16. `Long-Term Memory Retrieval`：长期记忆检索入口，基于语义检索和规则融合召回历史事实。
17. `MemorySearchService`：长期检索服务，编排 query rewrite、融合、重排、时间语义排序和反馈打点。
18. `RetrievalPipeline`：检索流水线核心，执行 vector/keyword 召回、fusion、rerank、post-filter。
19. `Vector Store`：向量检索后端抽象（默认 pgvector，可切 FAISS/Milvus/Qdrant）。
20. `Keyword Retriever`：关键词检索后端（BM25/TF-IDF），用于补充向量召回盲区。
21. `MemoryIngestionService`：长期记忆摄入服务，负责分块、向量化、去重和入库。
22. `Long-Term Memory Store`：长期记忆实体层（`memory_chunks/memory_facts/memory_mentions` 及生命周期表）。
23. `PostgreSQL + pgvector`：主存储与默认向量能力承载层。
24. `OnlineEvaluationService`：在线评测闭环服务，记录 writing/retrieval 事件并生成日聚合指标。
25. `evaluation_runs/events/daily`：评测持久化层，存 run 级、event 级和 daily 级指标。
26. `apps/orchestrator/worker.py`：后台执行进程，轮询队列并推动 orchestrator 运行。
27. `scripts/run_lifecycle_scheduler.py`：生命周期调度入口，触发 embedding pending、forgetting、rebuild。
28. `MemoryForgettingService`：遗忘服务，按策略下调/归档/删除长期记忆，控制记忆膨胀。
29. `MemoryRebuildService`：重建服务，对陈旧或不一致索引执行修复和重建。
30. `RetrievalLoopService`：检索驱动执行循环，负责“计划检索 -> 证据评估 -> 继续/停止”，统一服务 `outline/chapter/consistency/revision`。
31. `retrieval_rounds/retrieval_evidence_items`：检索回放持久化层，记录每轮 query/决策/覆盖率/证据明细，用于可追踪与可回放。

### 1.2 统一调度器是谁负责

- **写作主调度器**：`packages/workflows/orchestration/service.py` 中的 `WritingOrchestratorService`。
- **执行进程**：`apps/orchestrator/worker.py`（`run_worker_once` / `run_worker_loop`，可选内嵌 lifecycle tick）。
- **生命周期调度器**：`scripts/run_lifecycle_scheduler.py`（独立批量入口，embedding/rebuild/forgetting）。

### 1.3 8 角色运行时映射

固定 8 角色并与 `apps/agents/*` 一一映射：
- `planner_agent`
- `retrieval_agent`
- `plot_agent`
- `character_agent`
- `world_agent`
- `style_agent`
- `writer_agent`
- `consistency_agent`

每个角色目录固定 4 个文件：
- `prompt.md`
- `strategy.yaml`
- `output_schema.json`
- `skills.yaml`

说明：`revision` 不是第 9 角色，而是 `writer_agent` 的 `revision` 策略模式。

---

## 2. 业务逻辑架构（运行时）

### 2.1 v2 全流程 DAG（默认）

默认步骤（Mock Planner 与真实 Planner 都遵循同一语义）：
1. `planner_bootstrap`
2. `retrieval_context`
3. `outline_generation`
4. 并行：`plot_alignment` / `character_alignment` / `world_alignment` / `style_alignment`
5. `writer_draft`（`chapter_generation`，会注入并行步骤产出的角色约束/世界硬规则/风格微约束/检索摘要）
6. `consistency_review`
7. `writer_revision`（`revision`）
8. `persist_artifacts`

### 2.1.1 检索驱动执行循环（统一接线）

四条工作流 `outline/chapter/consistency/revision` 均接入同一循环：
1. 计划检索（生成 `query/intent/source_types/must_have_slots`）
2. 执行检索（结构化硬约束 + 长期记忆证据）
3. 证据评估（`coverage_score/resolved_slots/open_slots/new_evidence_gain`）
4. 决策继续或停止

默认停止策略：
- `WRITER_RETRIEVAL_MAX_ROUNDS=20`
- `WRITER_RETRIEVAL_ROUND_TOP_K=8`
- `WRITER_RETRIEVAL_MAX_UNIQUE_EVIDENCE=64`
- 达到覆盖阈值且连续低增益轮次达标时提前停止
- 或达到 `enough_context=true` 时停止

每一步都落审计：
- `workflow_steps`
- `agent_runs`
- `tool_calls`
- `skill_runs`
- `retrieval_rounds`
- `retrieval_evidence_items`
- `agent_messages`

审计增强字段：`role_id`、`strategy_version`、`prompt_hash`、`schema_version`。

### 2.2 长期记忆主流程

- 摄入：分块（默认带 overlap）-> 分块摘要（summary_text）-> embedding -> 去重（fact/mention）-> 写入 `memory_chunks/memory_facts/memory_mentions`。
- 检索：query rewrite -> vector + keyword -> fusion -> rerank -> post-filter。
- 生命周期：`embedding_jobs`、`rebuild`、`forgetting` 三个任务由调度脚本接入正式运行路径。

### 2.2.2 检索策略细节（最近更新）

1. **默认策略**：混合检索 + 重排  
   - 默认 `enable_hybrid=true`、`enable_rerank=true`，即 `vector + keyword` 融合后再做 rerank。

2. **`max_distance` 场景下的关键词分支**（关键更新）  
   - 向量分支继续受 `max_distance` 约束。  
   - 关键词分支仍参与 hybrid 召回（不被向量阈值直接裁掉），用于缓解“纯语义近邻但任务不相关”问题。

3. **中文关键词检索增强**  
   - `SimpleAnalyzer` 支持 `jieba(可选) + CJK 2/3-gram`，避免中文整句 token 化导致 BM25/TF-IDF 失真。
   - PostgreSQL FTS 无命中时，仓储层仍有 CJK fallback 兜底。

4. **规则重排增强（rule rerank）**  
   - 新增 `query_overlap` 信号：提高与查询槽位/关键词重叠高的候选。  
   - 新增 `contradiction_penalty`：对“误报/不涉及/无直接推进/暂时中止”等否定或弱相关语义做惩罚，降低噪声项排位。

5. **阈值回退链路**  
   - 严格阈值无命中时，按 `strict -> relaxed -> adaptive -> lexical` 回退，保证可用性。

### 2.2.1 上下文压缩策略（混合式，默认启用）

- 第一层（本地）：`summary_hint -> extractive -> truncate`，确保稳定和低延迟。
- 第二层（LLM 增强）：当压缩比不足或出现硬截断时，触发 `llm_abstractive`。
- 安全回退：LLM 异常、超预算或保真校验失败时，自动回退本地压缩结果。
- 保真校验：数字不新增、query 关键词覆盖、最小信息密度检查。

### 2.3 语义时间排序是否支持

支持，检索层具备语义时间过滤与排序能力：
- 过滤：`source_timestamp_gte` / `source_timestamp_lte` / `recent_within_days`
- 排序：
  - `relevance`
  - `relevance_then_recent`
  - `recent`
  - `timeline_asc`

对应实现：
- `packages/memory/long_term/search/search_service.py`
- `packages/retrieval/pipeline.py`
- `packages/memory/long_term/temporal/source_timestamp.py`

### 2.4 session.py 与 session_memory.py 的关系

- `packages/storage/postgres/session.py`：数据库 Session 工厂。
- `packages/memory/short_term/session_memory.py`：短期会话记忆逻辑。

两者属于不同层：一个是数据访问基础设施，一个是记忆业务模块；没有强耦合关系。

---

## 3. 项目结构（目录）

```text
apps/        API、agent 配置、worker 入口、web 前端（apps/web）
packages/    核心业务代码（memory/retrieval/workflow/evaluation/storage）
migrations/  Alembic 迁移
scripts/     运维脚本、集成测试、门禁脚本
tests/       单元测试
docs/        设计与运行文档
infra/       docker 等基础设施
```

---

## 4. API 说明

### 4.1 健康检查
- `GET /healthz`

### 4.2 v1 兼容接口（默认关闭）
- `POST /v1/projects/{project_id}/chapters/generate`（仅当 `WRITER_API_V1_ENABLED=1` 时启用）
  - 关键请求字段：
    - `include_memory_top_k`：检索候选数量上限（默认 8）
    - `context_token_budget`：工作记忆预算（可选，范围 `400~12000`；不传时走服务默认）

### 4.3 v2 鉴权与权限
- `POST /v2/auth/register`
- `POST /v2/auth/login`
- `POST /v2/auth/refresh`
- `POST /v2/auth/logout`
- `GET /v2/auth/me`
- 项目级 RBAC：
  - `owner`：成员管理、webhook 管理、项目高危操作。
  - `editor`：创建/推进写作 run、审批候选稿、编辑故事资产。
  - `viewer`：查询项目、run、评测、检索回放。

### 4.4 v2 项目与资产
- `POST /v2/projects`
- `GET /v2/projects`
- `GET/PATCH/DELETE /v2/projects/{project_id}`
- `POST /v2/projects/{project_id}/bootstrap`
- 角色/世界观/时间线/伏笔 CRUD：
  - `/v2/projects/{project_id}/characters*`
  - `/v2/projects/{project_id}/world-entries*`
  - `/v2/projects/{project_id}/timeline-events*`
  - `/v2/projects/{project_id}/foreshadowings*`
- 章节 CRUD 与版本管理：
  - `/v2/projects/{project_id}/chapters*`
  - `/v2/projects/{project_id}/chapters/{chapter_id}/versions`
  - `/v2/projects/{project_id}/chapters/{chapter_id}/publish`
  - `/v2/projects/{project_id}/chapters/{chapter_id}/rollback/{version_no}`

### 4.5 v2 写作编排主线
- `POST /v2/projects/{project_id}/writing/runs`
- `GET /v2/writing/runs/{run_id}`
- `WS /v2/writing/runs/{run_id}/ws?cursor=<seq>`（run 级实时事件流，支持 cursor 恢复）
- `POST /v2/writing/runs/{run_id}/cancel`
- `POST /v2/writing/runs/{run_id}/retry`
- `POST /v2/projects/{project_id}/workflows/{type}/runs`
- `GET /v2/projects/{project_id}/outlines/latest`
- `GET /v2/projects/{project_id}/consistency-reports`
- 关键请求字段：
  - `include_memory_top_k`：检索候选数量上限（默认 8）
  - `context_token_budget`：工作记忆预算（可选，范围 `400~12000`）
  - `session_id`：可选，会自动注入短期记忆（会话消息）

### 4.6 v2 候选稿审校（先审后存）
- `GET /v2/projects/{project_id}/chapter-candidates`
- `POST /v2/projects/{project_id}/chapter-candidates/{candidate_id}/approve`
- `POST /v2/projects/{project_id}/chapter-candidates/{candidate_id}/reject`
- 运行状态新增 `waiting_review`：
  - 候选稿生成后，run 进入 `waiting_review` 并暂停。
  - `approve` 后落正式章节/版本/长期记忆，再恢复后续步骤。
  - `reject` 可取消 run 或继续保持 `waiting_review`。

### 4.7 v2 会话域
- `POST /v2/projects/{project_id}/sessions`
- `GET /v2/projects/{project_id}/sessions`
- `POST /v2/projects/{project_id}/sessions/{session_id}/messages`
- `GET /v2/projects/{project_id}/sessions/{session_id}/messages`
- `POST /v2/projects/{project_id}/sessions/{session_id}/summarize`
- `POST /v2/projects/{project_id}/sessions/{session_id}/link-run/{run_id}`

### 4.8 v2 反馈与评测
- `POST /v2/retrieval/feedback`（兼容入口）
- `POST /v2/projects/{project_id}/evaluation/feedback`
- `GET /v2/projects/{project_id}/evaluation/daily`
- `GET /v2/projects/{project_id}/evaluation/runs/{run_id}`
- `POST /v2/projects/{project_id}/users/{user_id}/preferences`

### 4.9 v2 webhook 与成员管理
- 成员：
  - `GET /v2/projects/{project_id}/members`
  - `PUT /v2/projects/{project_id}/members/{member_user_id}`
  - `DELETE /v2/projects/{project_id}/members/{member_user_id}`
- webhook：
  - `POST /v2/projects/{project_id}/webhooks`
  - `GET /v2/projects/{project_id}/webhooks`
  - `PATCH/DELETE /v2/projects/{project_id}/webhooks/{subscription_id}`
  - `GET /v2/projects/{project_id}/webhooks/deliveries`

### 4.10 v2 运维与数据迁移
- 指标与备份：
  - `GET /v2/system/metrics`
  - `GET /v2/system/metrics/json`（结构化指标，前端控制台直连）
  - `POST /v2/system/backups/full`
  - `GET /v2/system/backups/latest`
  - `GET /v2/system/backups/runs`
- 导入导出：
  - `POST /v2/projects/{project_id}/exports`
  - `GET /v2/exports/{job_id}`
  - `POST /v2/projects/imports`
  - 导出默认 `include_long_term_memory=false`，可显式打开。

`context_token_budget` 生效优先级：
1. 请求显式传入（最高优先）
2. `WRITER_MEMORY_CONTEXT_TOKEN_BUDGET_DEFAULT`
3. 服务内部兜底（3200）

`GET /v2/writing/runs/{run_id}` 额外返回：
- `retrieval_rounds`
- `retrieval_stop_reason`
- `evidence_coverage`
- `open_slots`
- `mock_mode`

---

## 5. 数据库设计（重点表）

### 5.1 编排与审计域
- `workflow_runs`
- `workflow_steps`
- `agent_messages`
- `agent_runs`
- `tool_calls`
- `skill_runs`
- `audit_events`

### 5.2 写作业务域
- `projects`
- `users`
- `project_memberships`
- `chapters`
- `chapter_versions`
- `chapter_candidates`（`pending/approved/rejected/expired`）
- `outlines`
- `consistency_reports`
- `characters`
- `world_entries`
- `timeline_events`
- `foreshadowings`
- `sessions`
- `session_messages`

### 5.3 记忆与生命周期域
- `memory_chunks`
- `memory_facts`
- `memory_mentions`
- `embedding_job_runs`
- `memory_rebuild_checkpoints`

说明：
- `memory_chunks.summary_text`：分块摘要字段，用于上下文压缩与关键词召回增强。
- `memory_facts.summary_text`：规范事实摘要字段，用于 canonical fact 的高密度上下文注入。

### 5.4 评测域（统一 retrieval + writing）
- `evaluation_runs`
- `evaluation_events`
- `evaluation_daily_metrics`

### 5.5 运维与外部集成域
- `auth_refresh_tokens`
- `backup_runs`
- `webhook_subscriptions`
- `webhook_deliveries`
- `project_transfer_jobs`

兼容保留：
- `retrieval_eval_events`
- `retrieval_eval_daily_stats`

---

## 6. 配置说明（核心环境变量）

### 6.1 LLM 文本生成
- `WRITER_LLM_USE_MOCK`
- `WRITER_LLM_FALLBACK_TO_MOCK`
- `WRITER_LLM_BASE_URL`
- `WRITER_LLM_API_KEY`
- `WRITER_LLM_MODEL`
- `WRITER_LLM_TIMEOUT`
- `WRITER_LLM_PROMPT_GUARD_ENABLED`
- `WRITER_LLM_CONTEXT_WINDOW_TOKENS`
- `WRITER_LLM_PROMPT_GUARD_OUTPUT_RESERVE_TOKENS`
- `WRITER_LLM_PROMPT_GUARD_OVERHEAD_TOKENS`
- `WRITER_LLM_PROMPT_GUARD_MAX_ATTEMPTS`
- `WRITER_LLM_PROMPT_GUARD_LLM_MAX_INPUT_CHARS`

关键机制（已实现）：
1. 默认使用 `json_object`；当请求携带 `response_schema` 时，自动启用结构化输出（`json_schema` 或 `function-calling`）。
2. 当 `use_function_calling=true` 且存在 `response_schema` 时，请求会注入 `tools/tool_choice`，强制模型按函数参数 schema 返回。
3. 发送前执行输入侧 pre-LLM schema 校验（`input_payload/input_schema`），防止无效 prompt 进入模型。
4. 统一执行 `validate -> repair -> retry`：若模型输出未通过 schema 校验，会自动注入校验错误发起修复重试（关键步骤默认开启）。

### 6.1.1 鉴权与安全
- `DATABASE_URL`（生产环境必须显式配置；禁止默认值）
- `WRITER_AUTH_JWT_SECRET`
- `WRITER_AUTH_JWT_ISSUER`
- `WRITER_AUTH_ACCESS_TTL_MINUTES`（默认 15）
- `WRITER_AUTH_REFRESH_TTL_DAYS`（默认 30）
- `WRITER_AUTH_ENFORCE_PROD_SECRET`（生产建议保持 `1`）
- `WRITER_ENV`（`prod/production` 时启用更严格安全校验）

### 6.2 Planner
- `WRITER_PLANNER_USE_MOCK`
- `WRITER_PLANNER_FALLBACK_TO_MOCK`
- `WRITER_PLANNER_BASE_URL`
- `WRITER_PLANNER_API_KEY`
- `WRITER_PLANNER_MODEL`
- `WRITER_PLANNER_TEMPERATURE`
- `WRITER_PLANNER_TIMEOUT`

### 6.3 Orchestrator / Registry / Eval
- `WRITER_ORCH_WORKER_POLL_INTERVAL`
- `WRITER_ORCH_WORKER_BATCH_SIZE`
- `WRITER_ORCH_MAX_STEP_SECONDS`
- `WRITER_ORCH_DEFAULT_MAX_RETRIES`
- `WRITER_ORCH_DEFAULT_RETRY_DELAY`
- `WRITER_ORCH_ENABLE_AUTO_WORKER`
- `WRITER_AGENT_CONFIG_ROOT`
- `WRITER_SCHEMA_ROOT`
- `WRITER_SCHEMA_STRICT`
- `WRITER_SCHEMA_DEGRADE_MODE`
- `WRITER_SKILL_CONFIG_ROOT`
- `WRITER_EVAL_ONLINE_ENABLED`
- `WRITER_EVAL_DAILY_CRON`
- `WRITER_WORKFLOW_RUN_TIMEOUT_SECONDS`
- `WRITER_API_V1_ENABLED`
- `WRITER_REVIEW_EXPIRE_HOURS`（候选稿过期时间，默认 72）
- `WRITER_WEBHOOK_ENABLED`
- `WRITER_WEBHOOK_BATCH_SIZE`

### 6.3.1 检索循环（Retrieve-Reason-Write）
- `WRITER_RETRIEVAL_MAX_ROUNDS`
- `WRITER_RETRIEVAL_ROUND_TOP_K`
- `WRITER_RETRIEVAL_MAX_UNIQUE_EVIDENCE`
- `WRITER_RETRIEVAL_STOP_MIN_COVERAGE`
- `WRITER_RETRIEVAL_STOP_MIN_GAIN`
- `WRITER_RETRIEVAL_STOP_STALE_ROUNDS`
- `WRITER_CONTEXT_CHAPTER_WINDOW_BEFORE`
- `WRITER_CONTEXT_CHAPTER_WINDOW_AFTER`

### 6.3.2 生命周期调度
- `WRITER_LIFECYCLE_ENABLED`
- `WRITER_LIFECYCLE_EMBEDDING_LIMIT`
- `WRITER_LIFECYCLE_REBUILD_LIMIT`
- `WRITER_LIFECYCLE_FORGET_LIMIT`
- `WRITER_LIFECYCLE_FORGET_DRY_RUN`

### 6.4 Retrieval
- `WRITER_RETRIEVAL_VECTOR_BACKEND`
- `WRITER_RETRIEVAL_QUERY_REWRITE_BACKEND`
- `WRITER_RETRIEVAL_KEYWORD_BACKEND`
- `WRITER_RETRIEVAL_FUSION_BACKEND`
- `WRITER_RETRIEVAL_HYBRID_BACKEND`
- `WRITER_RETRIEVAL_RERANK_BACKEND`

### 6.5 Embedding 服务
- `EMBEDDING_SERVICE_BASE_URL`
- `EMBEDDING_API_KEY`
- `EMBEDDING_MODEL`
- `EMBEDDING_TIMEOUT`

### 6.5.1 记忆压缩与分块参数
- `WRITER_MEMORY_CHUNK_SIZE`
- `WRITER_MEMORY_CHUNK_OVERLAP`
- `WRITER_MEMORY_SUMMARY_TARGET_TOKENS`
- `WRITER_MEMORY_CONTEXT_COMPRESS_ENABLE_LLM`
- `WRITER_MEMORY_CONTEXT_COMPRESS_LLM_TRIGGER_RATIO`
- `WRITER_MEMORY_CONTEXT_COMPRESS_LLM_MIN_GAIN_RATIO`
- `WRITER_MEMORY_CONTEXT_COMPRESS_LLM_MAX_INPUT_CHARS`
- `WRITER_MEMORY_CONTEXT_COMPRESS_LLM_MAX_ITEMS`
- `WRITER_MEMORY_CONTEXT_TOKEN_BUDGET_DEFAULT`
- `WRITER_MEMORY_CONTEXT_MIN_RELEVANCE_SCORE`
- `WRITER_MEMORY_CONTEXT_RELATIVE_SCORE_FLOOR`
- `WRITER_MEMORY_CONTEXT_MIN_KEEP_ROWS`
- `WRITER_MEMORY_CONTEXT_MAX_ROWS`

预设参考：
- `docs/runbooks/context_retrieval_presets.md`
- `docs/runbooks/presets/context_retrieval_conservative.env`
- `docs/runbooks/presets/context_retrieval_balanced.env`
- `docs/runbooks/presets/context_retrieval_aggressive.env`

### 6.5.2 上下文门控策略（新增）

`ContextBuilder` 在检索结果进入 LLM 前执行两段式门控：
1. **候选限流**：先截断到 `WRITER_MEMORY_CONTEXT_MAX_ROWS`。
2. **动态阈值过滤**：
   - 先计算每条候选的置信度（优先 `rerank_score`，其次 `hybrid/keyword` 归一化，再次 `distance` 映射）。
   - 过滤阈值为：`max(WRITER_MEMORY_CONTEXT_MIN_RELEVANCE_SCORE, anchor * WRITER_MEMORY_CONTEXT_RELATIVE_SCORE_FLOOR)`，其中 `anchor` 为当前批次最高置信度。
   - 若过滤后不足 `WRITER_MEMORY_CONTEXT_MIN_KEEP_ROWS`，则按置信度回填到最小保留条数。

该策略的目标是：在保证召回不至于归零的前提下，尽量阻止低价值噪声证据进入最终上下文。

### 6.5.3 预设建议

1. **保守档**（质量优先）：生产环境、一致性要求高。
2. **均衡档**（推荐默认）：大多数写作任务。
3. **激进档**（召回优先）：信息不完整、前期探索。

### 6.6 配置文件总览（按生效链路）

#### 全局与基础设施
- `alembic.ini`：Alembic 迁移配置（迁移脚本路径、数据库连接等）。
- `infra/docker/docker-compose.yml`：本地依赖服务编排配置（数据库等基础组件）。

#### Agent 角色配置（8 角色，目录结构一致）
- `apps/agents/<role>/prompt.md`：角色系统提示词主文本。
- `apps/agents/<role>/strategy.yaml`：角色执行策略（`version/temperature/max_tokens/mode/mode_strategies`）。
- `apps/agents/<role>/skills.yaml`：角色绑定的技能 ID 列表（由 `SkillRegistry` 解析）。
- `apps/agents/<role>/output_schema.json`：角色输出 schema（支持两种写法：`schema_ref/schema_version` 引用模式，或“完整 JSON Schema”内联模式）。

当前角色目录：
- `apps/agents/planner_agent/`
- `apps/agents/retrieval_agent/`
- `apps/agents/plot_agent/`
- `apps/agents/character_agent/`
- `apps/agents/world_agent/`
- `apps/agents/style_agent/`
- `apps/agents/writer_agent/`
- `apps/agents/consistency_agent/`

#### Schema 配置（运行时强校验）
- `packages/schemas/agents/agent_profile.schema.json`：角色 profile 结构约束。
- `packages/schemas/agents/agent_strategy.schema.json`：角色策略结构约束。
- `packages/schemas/agents/agent_step_output.schema.json`：角色步骤输出结构约束。
- `packages/schemas/tools/skill_manifest.schema.json`：技能 manifest 结构约束。
- `packages/schemas/api/evaluation_feedback.schema.json`：评测反馈接口入参约束。
- `packages/schemas/evaluation/evaluation_event.schema.json`：评测事件数据约束。

#### Prompt 契约说明（输入/输出怎么告诉模型）
- 输入语义契约：在 workflow 构造的 `user_prompt` JSON 里表达（例如 `memory_context`、`retrieval_context`、`story_constraints`），并配合角色 `prompt.md` 说明字段语义。
- 输出结构契约：由 `response_schema` 注入模型（`json_schema`/`function-calling`），并在返回后再走本地 `validate` 校验。
- 角色化步骤的 schema 来源：`apps/agents/<role>/output_schema.json`（可内联）或 `apps/agents/<role>/output_schema.json -> packages/schemas/*.schema.json`（引用），两者都由运行时统一接线。

#### Skill 配置（运行时可装配能力）
- `packages/skills/*/manifest.json`：技能清单，覆盖 plot/character/world/style/retrieval/planner/writer/consistency 等角色能力。
- 这些 `manifest.json` 描述技能的 `id/name/version/description/tags`，由 `SkillRegistry` 严格加载并绑定到角色。

### 6.7 配置优先级与生效规则

1. 环境变量优先：`WRITER_*`、`EMBEDDING_*` 决定运行模式、模型开关、路径和超时等。
2. 角色目录配置次之：`apps/agents/*` 决定角色提示词、策略、技能与输出约束。
3. Schema/Skill 注册表负责校验与装配：  
`WRITER_SCHEMA_STRICT=1` 时违规直接失败；`WRITER_SCHEMA_DEGRADE_MODE=1` 时降级为 warning 并继续。
4. 规划阶段与执行阶段均走角色配置：  
`planner.py` 现已优先读取 `apps/agents/planner_agent/prompt.md`；  
执行阶段由编排器按 `role_id` 解析对应角色配置。

说明：仓库未提交 `.env` 文件，建议在部署环境通过系统环境变量注入配置。

---

## 7. 运行与运维

### 7.1 部署前准备

推荐基础环境：
- Python `3.11+`
- Node.js `20+`（已验证 `25.x` 可用）
- PostgreSQL `15+` + `pgvector`

初始化依赖：

```bash
# 后端
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# 前端（monorepo 根目录）
npm install
```

### 7.2 后端本地部署（API + Worker）

最小可跑环境变量（建议先 mock 跑通）：

```bash
export DATABASE_URL='postgresql+psycopg2://writer:writer@127.0.0.1:5432/writeragent'
export WRITER_AUTH_JWT_SECRET='replace-this-in-prod'
export WRITER_LLM_USE_MOCK=1
export WRITER_PLANNER_USE_MOCK=1
```

执行迁移并启动：

```bash
./venv/bin/alembic upgrade head
./venv/bin/uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
```

单独终端启动 worker（必需，否则 run 不会推进）：

```bash
./venv/bin/python scripts/run_orchestrator_worker.py
```

### 7.3 前端本地部署（apps/web）

前端默认通过 BFF 代理后端，配置后端地址：

```bash
export BACKEND_BASE_URL='http://127.0.0.1:8000'
npm run web:dev
```

访问：
- `http://127.0.0.1:3000/login`：登录页
- `http://127.0.0.1:3000/projects`：项目工作台
- `http://127.0.0.1:3000/runs/<run_id>`：Run 实时时间线（WebSocket）
- `http://127.0.0.1:3000/metrics`：专业控制台（结构化指标 + API 能力面板）

### 7.4 使用流程（从登录到写作闭环）

1. 登录（UI 或 API）  
   - UI：`/login`
   - API：`POST /v2/auth/login`
2. 创建项目：`POST /v2/projects`
3. 发起写作 run：`POST /v2/projects/{project_id}/writing/runs`
4. 观察 run：`GET /v2/writing/runs/{run_id}` 或 `WS /v2/writing/runs/{run_id}/ws`
5. 若状态为 `waiting_review`，处理候选稿：
   - 通过：`POST /v2/projects/{project_id}/chapter-candidates/{candidate_id}/approve`
   - 拒绝：`POST /v2/projects/{project_id}/chapter-candidates/{candidate_id}/reject`
6. Run 完成后查询章节与版本：
   - `GET /v2/projects/{project_id}/chapters`
   - `GET /v2/projects/{project_id}/chapters/{chapter_id}/versions`

### 7.5 生产部署建议

最小拓扑建议：
- 进程 A：`uvicorn apps.api.main:app`（多 worker）
- 进程 B：`python scripts/run_orchestrator_worker.py`
- 可选进程 C（定时）：`python scripts/run_lifecycle_scheduler.py`
- 反向代理：Nginx/ALB（HTTPS、超时、限流）

技能执行策略默认已是 `active`。若线上回滚某个 skill：

```bash
export SKILL_<SKILL_NAME>_EXECUTION_MODE=legacy
```

其中 `<SKILL_NAME>` 需使用大写下划线键（例如 `CONSTRAINT_ENFORCEMENT`）。

### 7.6 运维命令与发布门禁

生命周期调度：

```bash
./venv/bin/python scripts/run_lifecycle_scheduler.py --project-id <project_uuid>
```

后端测试：

```bash
./venv/bin/python -m pytest tests/unit tests/integration -q
```

前端测试与构建：

```bash
npm run web:test
npm run web:build
```

发布门禁：

```bash
./venv/bin/python scripts/release_gate.py --allow-missing-metrics
```

---

## 8. 文件讲解（按目录）

说明：以下为当前核心业务文件讲解，`__pycache__/.DS_Store` 等缓存文件不在讲解范围内。

### 8.1 `apps/`

- `apps/__init__.py`：应用层包初始化。
- `apps/api/__init__.py`：API 子包初始化。
- `apps/api/main.py`：FastAPI 入口，默认 v2 路由（v1 兼容路由可开关启用）、依赖装配、错误映射。
- `apps/orchestrator/__init__.py`：worker 包初始化。
- `apps/orchestrator/worker.py`：异步编排 worker 单轮/循环执行，支持可配置 lifecycle tick。
- `apps/web/`：Next.js 前端（工作台 + 专业控制台 + BFF 代理层）。
  - `apps/web/app/`：页面与 BFF route handlers（`/api/*`）。
  - `apps/web/modules/`：业务模块（projects/runs/console/rbac）。
  - `apps/web/server/bff/`：后端代理、token 轮换、HttpOnly Cookie 管理。

#### `apps/agents/*`（8 角色配置）
- `apps/agents/planner_agent/prompt.md`：规划器角色提示词。
- `apps/agents/planner_agent/strategy.yaml`：规划策略参数。
- `apps/agents/planner_agent/output_schema.json`：输出 schema（引用或内联）。
- `apps/agents/planner_agent/skills.yaml`：角色技能绑定。
- `apps/agents/retrieval_agent/prompt.md`：检索代理提示词。
- `apps/agents/retrieval_agent/strategy.yaml`：检索策略参数。
- `apps/agents/retrieval_agent/output_schema.json`：检索输出 schema（引用或内联）。
- `apps/agents/retrieval_agent/skills.yaml`：检索技能绑定。
- `apps/agents/plot_agent/prompt.md`：剧情代理提示词。
- `apps/agents/plot_agent/strategy.yaml`：剧情策略参数。
- `apps/agents/plot_agent/output_schema.json`：剧情输出 schema（引用或内联）。
- `apps/agents/plot_agent/skills.yaml`：剧情技能绑定。
- `apps/agents/character_agent/prompt.md`：角色一致性代理提示词。
- `apps/agents/character_agent/strategy.yaml`：角色策略参数。
- `apps/agents/character_agent/output_schema.json`：角色输出 schema（引用或内联）。
- `apps/agents/character_agent/skills.yaml`：角色技能绑定。
- `apps/agents/world_agent/prompt.md`：世界观代理提示词。
- `apps/agents/world_agent/strategy.yaml`：世界观策略参数。
- `apps/agents/world_agent/output_schema.json`：世界观输出 schema（引用或内联）。
- `apps/agents/world_agent/skills.yaml`：世界观技能绑定。
- `apps/agents/style_agent/prompt.md`：文风代理提示词。
- `apps/agents/style_agent/strategy.yaml`：文风策略参数。
- `apps/agents/style_agent/output_schema.json`：文风输出 schema（引用或内联）。
- `apps/agents/style_agent/skills.yaml`：文风技能绑定。
- `apps/agents/writer_agent/prompt.md`：主写作代理提示词（草稿/修订共用）。
- `apps/agents/writer_agent/strategy.yaml`：writer 双模式策略（`draft`/`revision`）。
- `apps/agents/writer_agent/output_schema.json`：writer 输出 schema（引用或内联）。
- `apps/agents/writer_agent/skills.yaml`：writer 技能绑定。
- `apps/agents/consistency_agent/prompt.md`：一致性审查代理提示词。
- `apps/agents/consistency_agent/strategy.yaml`：一致性策略参数。
- `apps/agents/consistency_agent/output_schema.json`：审查输出 schema（引用或内联）。
- `apps/agents/consistency_agent/skills.yaml`：一致性技能绑定。

### 8.2 `docs/`

- `docs/memory_forgetting_design.md`：遗忘机制设计文档。
- `docs/retrieval_release_checklist.md`：检索上线检查清单。
- `docs/writeragent_todo_status.md`：阶段任务与待办状态。

### 8.3 `infra/`

- `infra/docker/docker-compose.yml`：本地依赖服务编排。

### 8.4 `migrations/`

- `migrations/README`：Alembic 使用说明。
- `migrations/env.py`：迁移环境装配。
- `migrations/script.py.mako`：迁移模板。
- `migrations/versions/c98141f97df1_init_tables.py`：初始表结构。
- `migrations/versions/7f2c2f1a9f61_memory_embedding_dim_to_1024.py`：向量维度升级。
- `migrations/versions/9b5b0f4e2c11_add_memory_fact_and_mention_tables.py`：事实/提及表。
- `migrations/versions/b4a5e6d9c2f1_add_source_timestamp_expression_index.py`：语义时间索引。
- `migrations/versions/d3c6f9a1b2e4_add_memory_chunks_fts_index.py`：全文索引。
- `migrations/versions/e8f1b2c3d4a5_expand_embedding_status_enum.py`：embedding 状态扩展。
- `migrations/versions/f2c3d4e5f6a7_add_retrieval_eval_and_lifecycle_tables.py`：检索评测与生命周期表。
- `migrations/versions/a4b5c6d7e8f9_add_agent_run_fk_on_tool_and_skill.py`：`tool_calls/skill_runs` 外键增强。
- `migrations/versions/b9d1e2f3a4b6_add_orchestrator_and_full_workflow_tables.py`：编排与全流程表。
- `migrations/versions/c4e8f1a2b3c4_add_agent_registry_and_evaluation_tables.py`：角色审计字段 + 统一评测表。
- `migrations/versions/e1f2a3b4c5d6_add_retrieval_round_tables.py`：检索回放轮次与证据明细表。
- `migrations/versions/a9f8e7d6c5b4_prelaunch_auth_review_webhook_session_transfer.py`：鉴权、候选审稿、webhook、会话、备份、导入导出与审计表。

### 8.5 `packages/core/`

- `packages/core/__init__.py`：core 聚合导出。
- `packages/core/config/__init__.py`：配置导出。
- `packages/core/config/env.py`：环境变量解析工具。
- `packages/core/errors/__init__.py`：错误导出。
- `packages/core/errors/base.py`：基础错误类型。
- `packages/core/logging/__init__.py`：日志导出。
- `packages/core/logging/structured.py`：结构化日志/计数器。
- `packages/core/tracing/__init__.py`：追踪导出。
- `packages/core/tracing/context.py`：`trace_id/request_id` 上下文。
- `packages/core/types/__init__.py`：公共类型导出。
- `packages/core/types/common.py`：通用类型定义。
- `packages/core/utils/__init__.py`：工具导出。
- `packages/core/utils/hashing.py`：稳定哈希工具。
- `packages/core/utils/simple_yaml.py`：轻量 YAML 解析。
- `packages/core/utils/text.py`：文本规范化与去重辅助。
- `packages/core/utils/time.py`：时间工具。

### 8.5.1 `packages/auth/`

- `packages/auth/runtime_config.py`：鉴权配置（JWT 密钥、TTL、安全开关）。
- `packages/auth/passwords.py`：PBKDF2 密码哈希与校验。
- `packages/auth/token.py`：JWT 签发、解析、刷新 token 逻辑。
- `packages/auth/service.py`：注册/登录/刷新/登出/鉴权服务。

### 8.6 `packages/evaluation/`

- `packages/evaluation/__init__.py`：评测域导出。
- `packages/evaluation/types.py`：评测类型定义。
- `packages/evaluation/service.py`：统一在线评测闭环服务。
- `packages/evaluation/retrieval/__init__.py`：检索评测子域导出。
- `packages/evaluation/retrieval/payloads.py`：检索 impression/feedback payload 构建。
- `packages/evaluation/writing/__init__.py`：写作评测子域导出。
- `packages/evaluation/writing/scoring.py`：写作分数拆解计算。
- `packages/evaluation/consistency/__init__.py`：一致性评测导出。
- `packages/evaluation/consistency/metrics.py`：一致性评测指标。
- `packages/evaluation/regression/__init__.py`：回归评测扩展位。

### 8.6.1 `packages/observability/` / `packages/system/` / `packages/webhooks/` / `packages/sessions/` / `packages/transfer/`

- `packages/observability/metrics.py`：内存指标采集与 Prometheus 文本渲染。
- `packages/system/audit_service.py`：关键操作审计写入服务。
- `packages/system/backup_service.py`：全量备份与备份文件校验。
- `packages/webhooks/service.py`：webhook 事件入队与签名。
- `packages/webhooks/delivery_runner.py`：webhook 投递重试执行器（指数退避/死信）。
- `packages/sessions/service.py`：会话创建、消息汇总、chat_turns 转换。
- `packages/transfer/service.py`：项目快照导入导出服务。

### 8.7 `packages/llm/`

#### embeddings
- `packages/llm/embeddings/base.py`：embedding provider 抽象。
- `packages/llm/embeddings/embedding_service_api.py`：外部本地 embedding API 对接。
- `packages/llm/embeddings/factory.py`：embedding provider 工厂。
- `packages/llm/embeddings/openai_compatible.py`：OpenAI 兼容 embedding provider。

#### text_generation
- `packages/llm/text_generation/__init__.py`：文本生成导出。
- `packages/llm/text_generation/base.py`：文本生成抽象与类型。
- `packages/llm/text_generation/factory.py`：mock/real 选择工厂。
- `packages/llm/text_generation/mock_provider.py`：确定性 mock 生成。
- `packages/llm/text_generation/openai_compatible.py`：OpenAI 兼容实现。
- `packages/llm/text_generation/runtime_config.py`：文本生成配置。

### 8.8 `packages/memory/`

- `packages/memory/__init__.py`：memory 聚合导出。

#### long_term
- `packages/memory/long_term/__init__.py`：长期记忆导出。
- `packages/memory/long_term/observability.py`：长期记忆日志/指标封装。
- `packages/memory/long_term/runtime_config.py`：长期记忆配置。
- `packages/memory/long_term/ingestion/__init__.py`：摄入模块导出。
- `packages/memory/long_term/ingestion/ingestion_service.py`：分块、embedding、落库、pending 批处理。
- `packages/memory/long_term/lifecycle/__init__.py`：生命周期导出。
- `packages/memory/long_term/lifecycle/embedding_jobs.py`：embedding 作业 runner。
- `packages/memory/long_term/lifecycle/rebuild.py`：重建任务与断点续跑。
- `packages/memory/long_term/lifecycle/forgetting.py`：遗忘策略执行。
- `packages/memory/long_term/search/__init__.py`：检索模块导出。
- `packages/memory/long_term/search/search_service.py`：统一检索门面（含新旧策略桥接、评测打点）。
- `packages/memory/long_term/search/hybrid_search.py`：legacy hybrid 实现（回退路径/A-B 路径）。
- `packages/memory/long_term/search/reranker.py`：legacy reranker（回退路径/A-B 路径）。
- `packages/memory/long_term/temporal/__init__.py`：时间语义导出。
- `packages/memory/long_term/temporal/source_timestamp.py`：语义时间标准化与排序辅助。

#### project_memory / short_term / working_memory
- `packages/memory/project_memory/__init__.py`：项目记忆导出。
- `packages/memory/project_memory/project_memory_service.py`：组装 long/short/working memory。
- `packages/memory/short_term/__init__.py`：短期记忆导出。
- `packages/memory/short_term/session_memory.py`：会话摘要/压缩。
- `packages/memory/working_memory/__init__.py`：工作记忆导出。
- `packages/memory/working_memory/context_builder.py`：上下文预算与拼装。

### 8.9 `packages/retrieval/`

- `packages/retrieval/__init__.py`：retrieval 聚合导出。
- `packages/retrieval/config.py`：检索配置。
- `packages/retrieval/constants.py`：常量。
- `packages/retrieval/errors.py`：检索错误定义。
- `packages/retrieval/types.py`：检索类型。
- `packages/retrieval/pipeline.py`：统一检索流水线。

#### chunking
- `packages/retrieval/chunking/base.py`：分块抽象。
- `packages/retrieval/chunking/factory.py`：分块工厂。
- `packages/retrieval/chunking/simple_text_chunker.py`：简单分块。
- `packages/retrieval/chunking/sentence_chunker.py`：句子分块。
- `packages/retrieval/chunking/semantic_chunker.py`：语义分块。
- `packages/retrieval/chunking/markdown_chunker.py`：Markdown 分块。
- `packages/retrieval/chunking/recursive_chunker.py`：递归分块。

#### embeddings
- `packages/retrieval/embeddings/base.py`：检索 embedding 抽象。
- `packages/retrieval/embeddings/cache.py`：embedding 缓存装饰器。
- `packages/retrieval/embeddings/factory.py`：检索 embedding 工厂。
- `packages/retrieval/embeddings/local_api.py`：本地 API embedding。
- `packages/retrieval/embeddings/openai_compatible.py`：OpenAI embedding。

#### evaluators
- `packages/retrieval/evaluators/dataset.py`：评测数据集结构。
- `packages/retrieval/evaluators/metrics.py`：Recall/MRR/NDCG。
- `packages/retrieval/evaluators/offline_eval.py`：离线评测。
- `packages/retrieval/evaluators/online_eval.py`：在线评测逻辑。
- `packages/retrieval/evaluators/online_eval_service.py`：legacy 在线评测服务。

#### hybrid / keyword / query_rewrite / rerank / vector / indexers
- `packages/retrieval/hybrid/base.py`：融合策略抽象。
- `packages/retrieval/hybrid/rrf_fusion.py`：RRF 融合。
- `packages/retrieval/hybrid/weighted_fusion.py`：加权融合。
- `packages/retrieval/keyword/analyzer.py`：文本分析器。
- `packages/retrieval/keyword/base.py`：关键词检索抽象。
- `packages/retrieval/keyword/bm25_retriever.py`：BM25 实现。
- `packages/retrieval/keyword/tfidf_retriever.py`：TF-IDF 实现。
- `packages/retrieval/query_rewrite/base.py`：改写抽象。
- `packages/retrieval/query_rewrite/rule_rewriter.py`：规则改写。
- `packages/retrieval/query_rewrite/llm_rewriter.py`：LLM 改写。
- `packages/retrieval/rerank/base.py`：重排抽象。
- `packages/retrieval/rerank/rule_based.py`：规则重排。
- `packages/retrieval/rerank/cross_encoder.py`：外部 cross-encoder 重排。
- `packages/retrieval/vector/base.py`：向量存储抽象。
- `packages/retrieval/vector/factory.py`：向量后端工厂。
- `packages/retrieval/vector/filters.py`：统一过滤表达式。
- `packages/retrieval/vector/pgvector_store.py`：PostgreSQL/pgvector 实现。
- `packages/retrieval/vector/faiss_store.py`：FAISS 适配。
- `packages/retrieval/vector/milvus_store.py`：Milvus 适配。
- `packages/retrieval/vector/qdrant_store.py`：Qdrant 适配。
- `packages/retrieval/indexers/base.py`：索引器抽象。
- `packages/retrieval/indexers/chapter_indexer.py`：章节索引器。
- `packages/retrieval/indexers/memory_indexer.py`：记忆索引器。
- `packages/retrieval/indexers/world_entry_indexer.py`：世界观索引器。
- `packages/retrieval/indexers/scheduler.py`：索引调度器。

### 8.10 `packages/schemas/`（运行时已接入）

- `packages/schemas/__init__.py`：schema 包导出。
- `packages/schemas/registry.py`：轻量 JSON schema 注册/校验器。
- `packages/schemas/agents/agent_profile.schema.json`：角色 profile schema。
- `packages/schemas/agents/agent_strategy.schema.json`：角色策略 schema。
- `packages/schemas/agents/agent_step_output.schema.json`：角色步骤输出 schema。
- `packages/schemas/tools/skill_manifest.schema.json`：技能 manifest schema。
- `packages/schemas/api/evaluation_feedback.schema.json`：评测反馈 API schema。
- `packages/schemas/evaluation/evaluation_event.schema.json`：评测事件 schema。

### 8.11 `packages/skills/`（运行时已接入）

- `packages/skills/__init__.py`：skills 包导出。
- `packages/skills/registry.py`：技能注册中心，加载并校验 manifest。
- `packages/skills/*/manifest.json`：包含基础技能与角色专用技能（如 `creative_writing`、`constraint_enforcement`、`logical_planning`、`semantic_relevance_scoring` 等），用于 `apps/agents/*/skills.yaml` 严格解析。

### 8.12 `packages/storage/postgres/`

- `packages/storage/postgres/__init__.py`：postgres 包导出。
- `packages/storage/postgres/base.py`：SQLAlchemy Base。
- `packages/storage/postgres/session.py`：DB session factory。
- `packages/storage/postgres/types.py`：自定义 PG 类型（含向量）。
- `packages/storage/postgres/vector_settings.py`：向量维度配置。

#### models
- `packages/storage/postgres/models/agent_message.py`：Agent 消息审计。
- `packages/storage/postgres/models/agent_run.py`：Agent 运行。
- `packages/storage/postgres/models/tool_call.py`：工具调用审计。
- `packages/storage/postgres/models/skill_run.py`：技能运行审计。
- `packages/storage/postgres/models/workflow_run.py`：工作流运行。
- `packages/storage/postgres/models/workflow_step.py`：工作流步骤。
- `packages/storage/postgres/models/project.py`：项目。
- `packages/storage/postgres/models/user.py`：用户。
- `packages/storage/postgres/models/project_membership.py`：项目成员与 RBAC 角色。
- `packages/storage/postgres/models/auth_refresh_token.py`：refresh token 持久化与撤销。
- `packages/storage/postgres/models/chapter.py`：章节。
- `packages/storage/postgres/models/chapter_version.py`：章节版本。
- `packages/storage/postgres/models/chapter_candidate.py`：候选稿（先审后存）。
- `packages/storage/postgres/models/outline.py`：大纲。
- `packages/storage/postgres/models/consistency_report.py`：一致性报告。
- `packages/storage/postgres/models/session.py`：会话主表。
- `packages/storage/postgres/models/session_message.py`：会话消息。
- `packages/storage/postgres/models/character.py`：角色设定。
- `packages/storage/postgres/models/world_entry.py`：世界观设定。
- `packages/storage/postgres/models/timeline_event.py`：时间线事件。
- `packages/storage/postgres/models/foreshadowing.py`：伏笔。
- `packages/storage/postgres/models/memory_chunk.py`：记忆分块。
- `packages/storage/postgres/models/memory_fact.py`：记忆事实。
- `packages/storage/postgres/models/memory_mention.py`：事实提及。
- `packages/storage/postgres/models/embedding_job_run.py`：embedding 作业记录。
- `packages/storage/postgres/models/memory_rebuild_checkpoint.py`：重建检查点。
- `packages/storage/postgres/models/retrieval_eval_event.py`：legacy 检索评测事件。
- `packages/storage/postgres/models/retrieval_eval_daily_stat.py`：legacy 检索日聚合。
- `packages/storage/postgres/models/retrieval_round.py`：检索轮次回放。
- `packages/storage/postgres/models/retrieval_evidence_item.py`：检索证据明细。
- `packages/storage/postgres/models/evaluation_run.py`：统一评测 run。
- `packages/storage/postgres/models/evaluation_event.py`：统一评测事件。
- `packages/storage/postgres/models/evaluation_daily_metric.py`：统一评测日聚合。
- `packages/storage/postgres/models/webhook_subscription.py`：webhook 订阅。
- `packages/storage/postgres/models/webhook_delivery.py`：webhook 投递与重试状态。
- `packages/storage/postgres/models/backup_run.py`：备份/恢复演练记录。
- `packages/storage/postgres/models/project_transfer_job.py`：导入导出作业。
- `packages/storage/postgres/models/audit_event.py`：高危变更审计日志。

#### repositories
- `packages/storage/postgres/repositories/base.py`：仓储基类。
- `packages/storage/postgres/repositories/project_repository.py`：项目仓储。
- `packages/storage/postgres/repositories/user_repository.py`：用户仓储。
- `packages/storage/postgres/repositories/project_membership_repository.py`：项目成员/RBAC 仓储。
- `packages/storage/postgres/repositories/auth_refresh_token_repository.py`：refresh token 仓储。
- `packages/storage/postgres/repositories/chapter_repository.py`：章节/版本仓储。
- `packages/storage/postgres/repositories/chapter_candidate_repository.py`：候选稿仓储。
- `packages/storage/postgres/repositories/outline_repository.py`：大纲仓储。
- `packages/storage/postgres/repositories/consistency_report_repository.py`：一致性报告仓储。
- `packages/storage/postgres/repositories/workflow_run_repository.py`：workflow run 仓储。
- `packages/storage/postgres/repositories/workflow_step_repository.py`：workflow step 仓储。
- `packages/storage/postgres/repositories/agent_message_repository.py`：消息仓储。
- `packages/storage/postgres/repositories/agent_run_repository.py`：agent run 仓储。
- `packages/storage/postgres/repositories/tool_call_repository.py`：tool call 仓储。
- `packages/storage/postgres/repositories/skill_run_repository.py`：skill run 仓储。
- `packages/storage/postgres/repositories/memory_repository.py`：memory chunk 仓储。
- `packages/storage/postgres/repositories/memory_fact_repository.py`：memory fact 仓储。
- `packages/storage/postgres/repositories/embedding_job_run_repository.py`：embedding 作业仓储。
- `packages/storage/postgres/repositories/memory_rebuild_checkpoint_repository.py`：重建检查点仓储。
- `packages/storage/postgres/repositories/retrieval_eval_repository.py`：legacy 检索评测仓储。
- `packages/storage/postgres/repositories/retrieval_trace_repository.py`：检索回放仓储（轮次/证据）。
- `packages/storage/postgres/repositories/evaluation_repository.py`：统一评测仓储。
- `packages/storage/postgres/repositories/session_repository.py`：会话与消息仓储。
- `packages/storage/postgres/repositories/webhook_subscription_repository.py`：webhook 订阅仓储。
- `packages/storage/postgres/repositories/webhook_delivery_repository.py`：webhook 投递仓储。
- `packages/storage/postgres/repositories/backup_run_repository.py`：备份 run 仓储。
- `packages/storage/postgres/repositories/project_transfer_job_repository.py`：导入导出作业仓储。
- `packages/storage/postgres/repositories/audit_event_repository.py`：审计日志仓储。

### 8.13 `packages/tools/`

- `packages/tools/__init__.py`：工具聚合（延迟导入）。
- `packages/tools/chapter_tools/chapter_generation_tool.py`：章节生成工具。
- `packages/tools/retrieval_tools/project_memory_tool.py`：项目记忆检索工具。
- `packages/tools/character_tools/context_tool.py`：角色上下文工具。
- `packages/tools/world_tools/context_tool.py`：世界观上下文工具。
- `packages/tools/consistency_tools/review_tool.py`：一致性审查工具。

### 8.14 `packages/workflows/`

- `packages/workflows/__init__.py`：workflow 聚合导出。

#### chapter_generation
- `packages/workflows/chapter_generation/context_provider.py`：章节上下文读取器。
- `packages/workflows/chapter_generation/types.py`：章节 workflow 请求/响应类型。
- `packages/workflows/chapter_generation/service.py`：章节生成流程。

#### outline_generation / consistency_review / revision
- `packages/workflows/outline_generation/service.py`：大纲生成流程。
- `packages/workflows/consistency_review/service.py`：一致性审查流程。
- `packages/workflows/revision/service.py`：章节修订流程。

#### orchestration
- `packages/workflows/orchestration/types.py`：编排类型定义。
- `packages/workflows/orchestration/runtime_config.py`：编排运行时配置。
- `packages/workflows/orchestration/planner.py`：动态规划器（Mock/真实模型）。
- `packages/workflows/orchestration/agent_registry.py`：角色配置注册/解析。
- `packages/workflows/orchestration/retrieval_loop.py`：检索循环服务（最多 20 轮、覆盖率停机、回放落库）。
- `packages/workflows/orchestration/service.py`：统一调度与步骤执行核心。

### 8.15 `scripts/`

- `scripts/_db_engine.py`：数据库引擎装配工具。
- `scripts/_chapter_workflow_support.py`：章节测试辅助。
- `scripts/_orchestrator_support.py`：编排测试辅助。
- `scripts/release_gate.py`：发布门禁脚本。
- `scripts/run_orchestrator_worker.py`：worker 启动脚本。
- `scripts/run_lifecycle_scheduler.py`：生命周期调度脚本。
- `scripts/backup_database.py`：触发全量备份并记录 `backup_runs`。
- `scripts/restore_database.py`：从 SQL 备份恢复（演练用途）。
- `scripts/verify_backup_restore.py`：备份文件校验/恢复演练记录。
- `scripts/run_memory_forgetting_job.py`：遗忘作业入口。
- `scripts/run_offline_retrieval_eval.py`：离线检索评测。
- `scripts/run_online_eval_summary.py`：在线评测汇总。
- `scripts/sync_vector_backend.py`：向量后端同步脚本。
- `scripts/test_project_repository.py`：项目仓储集成测试。
- `scripts/test_chapter_repository.py`：章节仓储集成测试。
- `scripts/test_memory_ingestion_service.py`：记忆摄入集成测试。
- `scripts/test_memory_dedup_pipeline.py`：记忆去重链路测试。
- `scripts/test_memory_search_service.py`：检索集成测试。
- `scripts/test_memory_forgetting_service.py`：遗忘集成测试。
- `scripts/test_retrieval_pipeline_contract.py`：检索契约测试。
- `scripts/test_chapter_generation_workflow.py`：章节 workflow 集成测试。
- `scripts/test_chapter_generation_api.py`：章节 API 集成测试。
- `scripts/test_writing_orchestrator_workflow.py`：编排 workflow 集成测试。
- `scripts/test_writing_orchestrator_api.py`：编排 API 集成测试。

### 8.16 `tests/unit/`

- `tests/unit/test_core_config.py`：配置解析测试。
- `tests/unit/test_core_errors_and_compat.py`：错误与兼容测试。
- `tests/unit/test_core_logging_and_tracing.py`：日志追踪测试。
- `tests/unit/test_core_runtime_config_compat.py`：运行时配置兼容测试。
- `tests/unit/test_auth_service.py`：认证服务（注册/登录/刷新/注销）单测。
- `tests/unit/test_text_generation_provider.py`：文本生成 provider 测试。
- `tests/unit/test_vector_store_factory.py`：向量工厂测试。
- `tests/unit/test_cross_encoder_reranker.py`：cross-encoder 重排测试。
- `tests/unit/test_retrieval_pipeline.py`：检索流水线测试。
- `tests/unit/test_retrieval_metrics.py`：检索指标测试。
- `tests/unit/test_offline_online_eval.py`：离线/在线评测测试。
- `tests/unit/test_online_eval_service.py`：legacy 在线评测服务测试。
- `tests/unit/test_embedding_job_runner.py`：embedding 作业测试。
- `tests/unit/test_rebuild_checkpoint.py`：重建断点测试。
- `tests/unit/test_session_and_context.py`：短期/工作记忆测试。
- `tests/unit/test_project_memory_service.py`：项目记忆聚合测试。
- `tests/unit/test_chapter_generation_workflow.py`：章节 workflow 单测。
- `tests/unit/test_orchestration_planner.py`：规划器单测。
- `tests/unit/test_agent_registry_runtime.py`：角色注册运行时测试。
- `tests/unit/test_orchestrator_runtime_config.py`：编排配置测试。
- `tests/unit/test_run_events.py`：run 事件序列构建与 cursor 过滤测试。
- `tests/unit/test_evaluation_service.py`：统一评测服务测试。
- `tests/unit/test_retrieval_loop_service.py`：检索循环状态机测试。
- `tests/integration/test_metrics_and_run_ws.py`：`metrics/json` 与 run WebSocket 集成测试。
- `tests/e2e/test_writing_run_review_flow.py`：登录 + 创建 run + 轮询终态 e2e（环境变量驱动）。

---

## 9. 当前状态

已完成：
- 8 角色主链接入运行时（非硬编码）。
- schema/skills registry 已在 orchestrator 主链启用。
- 统一在线评测闭环（run/event/daily）已落库并暴露 API。
- `outline -> chapter -> consistency -> revision` 全链路可跑。
- 四条 workflow 均已接入检索循环（最多 20 轮、覆盖率停机、低增益停机）。
- 检索回放表 `retrieval_rounds/retrieval_evidence_items` 已接通 run detail 回放。
- `users.preferences` 已接入写作上下文并支持更新后触发记忆重建。
- 记忆摄入/检索/遗忘/重建与生命周期调度已接线。
- 鉴权已升级为 `JWT + 项目级 RBAC`，并新增项目成员管理接口。
- 写作链路已切换为“先审后存”：候选稿 + `waiting_review` + approve/reject。
- webhook 事件回调（含签名、重试、死信）已上线并接入 worker。
- 会话域（session/session_messages）已接入 run 入参，支持自动注入短期记忆。
- 导入导出与备份恢复能力已上线，并有对应系统 API 与脚本。
- 安全基线已增强：生产环境默认 DB URL 防误用、日志敏感字段脱敏。
- release gate 已覆盖 workflow、API、retrieval、forgetting，并新增备份/恢复指标门禁。
