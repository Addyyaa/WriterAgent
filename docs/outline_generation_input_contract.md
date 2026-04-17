# outline_generation 输入/输出合同

本文描述 [`OutlineGenerationWorkflowService`](packages/workflows/outline_generation/service.py) 与编排层 [`_run_outline_step`](packages/workflows/orchestration/service.py) 之间的载荷约定。

## 编排层职责

- **`writing_goal`**：仅用户意图字符串，**不**再拼接检索扁平正文 `context_text`。
- **`outline_intake`**：单次结构化灌入，取代顶层 `retrieval_context` 与「goal 内嵌证据」的重复。
- 证据来源：`RetrievalLoopSummary.context_bundle`，经 `read_decision_fields_from_bundle` / `read_key_facts_from_bundle` 读取，并在编排侧做条数与单条长度截断。

## `outline_intake` 字段

| 字段 | 说明 |
|------|------|
| `project_brief` | `id` / `title` / `genre`、截断 `premise`（约 1400 字）、`metadata_json` 白名单：`current_arc_brief`、`current_chapter_position_brief`、`series_brief` |
| `target_chapter_position` | `chapter_no`（`input_json` 或 `get_next_chapter_no`）、`target_words`、`arc_stage`、`next_hook_type`（与 plot 分支兼容键一致） |
| `prior_chapter_summary` | 上一章 `chapter_no` / `title` / `summary`，首章为 `null` |
| `confirmed_facts` | 已确认事实（截断列表） |
| `current_states` | 当前叙事状态 |
| `supporting_evidence` | 决策层 supporting + 少量 `items[]` 摘录 |
| `conflicts` | 冲突或未决 |
| `information_gaps` | 待核实缺口（**不得**当事实使用） |
| `key_facts` | 关键事实 |

列表上限与字符上限由编排实现定义（与 Assembler 检索视图量级相近），以控制 token。

## LLM 输入 JSON（user）

- `writing_goal`、`style_hint`、`outline_intake`、`output_schema`（输出形状说明，非严格校验主体）。
- **不再包含**全量 `project` 对象或长字符串 `retrieval_context`。

## 输出

- **顶层**：`title`、`content`、`structure_json`。
- **`content`**：仅 **outline synopsis**（章节事件梗概 + 推进理由 + 章末钩子），`maxLength` 约 4000；禁止当正文半成稿。
- **`structure_json`（必填键）**：
  - `chapter_goal`、`core_conflict`、`end_hook`
  - `must_preserve_facts`、`open_questions`、`assumptions_used`（数组）
  - `acts`、`character_arcs`、`foreshadowing_plan`
- 若模型输出缺字段，服务层会 **补齐** 并记录日志 `event: outline_structure_json_coerced`。

## System 合同

见 [`apps/agents/outline_generation/prompt_system.md`](../apps/agents/outline_generation/prompt_system.md)。

## 相关代码

- [`packages/workflows/outline_generation/service.py`](../packages/workflows/outline_generation/service.py) — IN/OUT JSON Schema、`_coerce_structure_json`
- [`packages/workflows/orchestration/service.py`](../packages/workflows/orchestration/service.py) — `_build_outline_generation_intake`、`_run_outline_step`
- [`docs/plot_agent_input_contract.md`](plot_agent_input_contract.md) — 下游 plot 消费的大纲形态（plot_beats）
