# Planner 槽位词表（与检索层一致）

`required_slots` / `global_required_slots` 的**闭集**由 `packages/workflows/orchestration/planner_slot_vocabulary.py` 中 `CANONICAL_PLANNER_SLOTS` 定义，与 `RetrievalLoopService._SLOT_SOURCE_MAP` 的键一一对应。

## 规范槽位

| 槽位 | 说明 |
|------|------|
| `project_goal` | 项目目标 |
| `outline` | 大纲 |
| `chapter_neighborhood` | 邻章、衔接 |
| `character` | 角色 |
| `world_rule` | 世界观规则 |
| `timeline` | 时间线 |
| `foreshadowing` | 伏笔 |
| `style_preference` | 风格偏好 |
| `conflict_evidence` | 冲突证据 |
| `inventory` / `current_inventory` / `character_inventory` | 物品与财富一致性 |
| `power_rules` / `power_rule` / `known_power_rules` | 规则/异能边界 |
| `scene` / `location` | 场景地点 |
| `relationship` / `witnesses` | 关系与目击者 |
| `previous_chapter` | 紧前章 |
| `story_state` / `scene_state` | 故事/场景状态 |

## 别名（服务端归一）

| 别名 | 规范槽位 |
|------|----------|
| `recent_trigger_events` | `timeline` |
| `recent_power_activations` | `timeline` |
| `scene_constraints` | `scene_state` |
| `wealth` / `current_wealth` | `current_inventory` |
| `chapter_1_content` / `chapter_2_content` / `chapter_N_content` | `chapter_neighborhood` |
| `chapter_position` | `chapter_neighborhood` |
| `story_timeline` | `timeline` |
| `scene_design` | `scene_state` |
| `conflict_points` | `conflict_evidence` |
| `used_items` | `current_inventory` |

**勿**将 `memory_fact`、`chapter`、`world_entry` 等数据源类型当作槽位；此类输入会被丢弃。

## 相关文件

- 归一实现：`planner_slot_vocabulary.normalize_planner_slot`
- 抽取合并：`planner_knowledge.extract_planner_retrieval_slots` / `merge_planner_retrieval_slots`
- 检索合并：`retrieval_loop.RetrievalLoopService._merge_inference_slots`
