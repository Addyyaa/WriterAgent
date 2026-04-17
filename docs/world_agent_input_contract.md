# world_agent / world_alignment 输入合同

## 目标

`world_alignment` 步骤使用 **world gatekeeper bundle**，避免 `project` 整包 premise、`outline` 全文与多层 `retrieval` 重复灌入。

## 编排依赖

- `world_alignment` 依赖 **`plot_alignment`**（与 `character_alignment` 一致），以便注入结构化章意图与节拍。

## LLM 输入顶层键

| 键 | 说明 |
|----|------|
| `world_lore_brief` | `title`、`genre`、`premise_excerpt`（截断）、精简 `metadata_json` |
| `chapter_world_slice` | `world_entries`、`retrieval_world_hints`、`locations`/`factions`/`items_concepts` 候选池、`notes` |
| `chapter_intent` | `chapter_no`、`chapter_title`、`arc_stage`、`chapter_goal`、`outline_beats`、`planned_conflicts`、`target_scene_types` 等 |
| `confirmed_world_facts` | 已确认事实与规则线索（含部分 supporting_evidence 摘录） |
| `chapter_applicable_states` | 与章意图相关的当前状态句（非缺口类） |
| `unresolved_gaps` | 缺口/冲突描述；**低权重**，不可等同硬事实 |

另含满足通用 Agent 输入 schema 的：`step_key`、`workflow_type`、`role_id`、`goal`、`state`（`world_input_contract_version`）、`local_data_tools`。

## 不出现

- 整份 `project.premise`
- `outline` 整块、`world_context`
- `retrieval` / `retrieval_decision` / `retrieval_summary` 并行重复

## Writer 依赖（不变）

`writer_draft` 仍从 `world_alignment` 视图消费：`world_logic_summary`、`hard_constraints`、`reusable_assets`、`potential_conflicts`。

## 日志

- `world_gatekeeper_chapter_no_missing`：无法解析有效 `chapter_no` 时警告。
