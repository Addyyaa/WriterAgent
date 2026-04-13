# Context & Retrieval Presets

本文件提供三档可直接使用的上下文预算与检索过滤预设，适用于长篇小说写作场景。

## 使用方式

1. 从 `docs/runbooks/presets/*.env` 选择一个预设文件。
2. 复制其内容到你的运行环境（或 `.env`）。
3. 重启 API / worker 进程。

## 预设说明

### 1) 保守（质量优先，最少噪声）
- 适合：生产环境、剧情一致性要求高
- 特点：强过滤、较小上下文预算、稳定但可能漏召回

### 2) 均衡（推荐默认）
- 适合：日常开发与多数写作任务
- 特点：质量与召回平衡

### 3) 激进（召回优先）
- 适合：前期探索、信息不完整场景
- 特点：更高召回、噪声也更多

## 关键参数解释

- `WRITER_MEMORY_CONTEXT_TOKEN_BUDGET_DEFAULT`：工作记忆默认预算（token）。
- `WRITER_MEMORY_CONTEXT_MIN_RELEVANCE_SCORE`：绝对置信度下限（0~1）。
- `WRITER_MEMORY_CONTEXT_RELATIVE_SCORE_FLOOR`：相对头部结果的比例阈值（0~1）。
- `WRITER_MEMORY_CONTEXT_MIN_KEEP_ROWS`：即使过滤严格也至少保留的检索行数。
- `WRITER_MEMORY_CONTEXT_MAX_ROWS`：进入上下文构建前的检索候选上限。
- `WRITER_RETRIEVAL_ROUND_TOP_K`：每轮检索召回上限（检索循环）。

