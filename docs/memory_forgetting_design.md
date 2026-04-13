# Memory Forgetting Design

本文档给出 WriterAgent 的长期记忆遗忘设计（可上线版本）。

## 1. 设计目标

1. 不直接“粗暴删除”，优先软遗忘（可恢复）。
2. 与现有 fact/mention 双层去重模型兼容。
3. 对检索链路透明：被遗忘内容默认不参与召回。
4. 支持 dry-run，先评估再执行，降低误删风险。

## 2. 核心思路（分层遗忘）

记忆生命周期阶段：

1. `active`：活跃，正常检索。
2. `cooling`：进入冷却期，仍可检索。
3. `suppressed`：抑制，默认不检索（可恢复）。
4. `archived`：归档，默认不检索（可恢复）。
5. `deleted`：硬删除（谨慎开启）。

执行原则：

1. 先软遗忘（`suppressed/archived`），默认不做硬删除。
2. 只有“很久未触达 + 提及次数低”的长尾事实才允许 `deleted`。
3. 命中去重的旧事实若被再次提及，自动清除遗忘标记并恢复检索可见性。

## 3. 评分与判定

候选分数由两部分构成：

1. `age_days`：距离 `last_seen_at` 的天数。
2. `mention_count`：事实累计提及次数。

当前实现分数：

```text
freq_factor = 1 / (1 + log1p(mention_count))
age_factor = min(3.0, age_days / 30.0)
score = age_factor * freq_factor
```

默认阈值（可配置）：

1. `cooling_days=7`
2. `suppress_days=30`
3. `archive_days=90`
4. `delete_days=180`
5. `min_mentions_to_keep=3`

保护条件（永不进入遗忘）：

1. `metadata_json.pin_memory=true`
2. `metadata_json.legal_hold=true`

## 4. 数据与检索层对齐

### 4.1 事实层（`memory_facts`）

在 `metadata_json` 写入：

1. `forgetting_stage`
2. `forgetting_reason`
3. `forgetting_score`
4. `forgotten_at`

### 4.2 检索层（`memory_chunks`）

对 `source_type="memory_fact"` 关联 chunk 同步写入相同遗忘标记。

检索默认排除阶段：

1. `suppressed`
2. `archived`
3. `deleted`

即使 embedding 状态仍为 `done`，也不会被召回。

## 5. 执行编排

入口：

1. `MemoryForgettingService.run_once(project_id, dry_run, allow_hard_delete)`

输出：

1. `ForgettingRunResult`（扫描数量、各阶段计数、决策详情）

动作：

1. `cooling/suppressed/archived`：写标记，不删除。
2. `deleted`：删除 `memory_fact` 及关联 `memory_chunks`（mention 通过 FK 级联删除）。

## 6. 恢复机制（关键）

当旧 fact 再次被提及时：

1. `upsert_fact_with_mention` 会清理事实层遗忘标记。
2. ingestion 会确保 canonical chunk 存在且状态可检索。
3. 若 chunk 曾被抑制/归档，会移除遗忘标记并恢复可见。

这保证“忘记是可逆的”，避免业务灾难性遗忘。

## 7. 运行建议

上线步骤：

1. 先 `dry_run=True` 连跑 7 天，观察分布。
2. 调整阈值后再开启真实执行（仍建议 `allow_hard_delete=False`）。
3. 稳定后再评估是否开放硬删除。

建议监控：

1. 每次 run 的 `scanned/cooled/suppressed/archived/deleted`
2. 遗忘后检索命中率变化
3. “恢复”事实数量（被再次提及后恢复可见）

## 8. 相关代码

1. `packages/memory/long_term/lifecycle/forgetting.py`
2. `packages/storage/postgres/repositories/memory_fact_repository.py`
3. `packages/storage/postgres/repositories/memory_repository.py`
4. `packages/memory/long_term/ingestion/ingestion_service.py`
5. `packages/memory/long_term/runtime_config.py`

