# plot_agent / plot_alignment 输入合同

本文描述编排层注入到 **plot_agent**（含 `step_key=plot_alignment`）的 LLM 用户载荷约定，便于前后端与 `projects.metadata_json` 对齐。实现见 `packages/workflows/orchestration/step_input_specs.py`、`prompt_payload_assembler.py`、`service.py`。

## 顶层结构（节选）

| 字段 | 说明 |
|------|------|
| `project` | `project_profile=plot_brief`：收窄后的项目视图 |
| `outline` | `outline_profile=plot_beats`：以 `structure_json` + 可选 `content_synopsis` 为主，无长正文 `content` |
| `state` | 仅含 `StepInputSpec.dependencies` 投影；plot **不含** `retrieval_context` 块 |
| `retrieval` / `retrieval_decision` | 同对象；唯一主检索决策包；`gap_treatment=soft_sidebar` 时缺口在 `soft_gaps.information_gaps` |
| `plot_context` | 章节与承接信息（见下表） |
| `goal` | `workflow_run.input_json.writing_goal` |
| **不含** | plot 步骤下 **无** `retrieval_summary`（避免与 `retrieval` 重复） |

## `project`（plot_brief）

| 字段 | 规则 |
|------|------|
| `id`, `title`, `genre` | 原样 |
| `premise` | 截断（约 1400 字，含省略号） |
| `metadata_json` | **白名单**：仅保留存在的键 `current_arc_brief`、`current_chapter_position_brief`、`series_brief`；其余键不进入 plot 载荷 |

说明：`current_arc_brief` 等为**短文案**，与 `plot_context.arc_stage`（阶段标签）不同；可同时存在。

## `outline`（plot_beats）

| 字段 | 规则 |
|------|------|
| `title` | 大纲标题 |
| `structure_json` | 结构化大纲（节拍设计的主依据） |
| `content_synopsis` | 可选；优先来自 `structure_json` 的 `synopsis` / `logline` / `one_line` / `elevator_pitch`，或 `outline.metadata_json` 中 `synopsis` / `logline`，否则由 `content` 截断生成 |
| `content` | **不出现**（长正文不注入 plot） |

## `retrieval`（plot 专用策略）

- `summary_only`；`gap_treatment=soft_sidebar`；`max_information_gaps=4`。
- 主驱动字段：`key_facts`、`current_states`、`confirmed_facts`、`supporting_evidence`、`conflicts`。
- 信息缺口：**不**与上述字段同级；统一放在 `soft_gaps.information_gaps`，条目前缀 `待核实：`（已有此前缀则不重复）。

## `plot_context`

| 字段 | 来源与规则 |
|------|------------|
| `chapter_no` | `input_json.chapter_no`；若缺失则由 `ChapterRepository.get_next_chapter_no(project_id)` 推断 |
| `target_words` | `input_json.target_words` |
| `previous_chapter_ref` | 当 `chapter_no > 1` 时：`get_by_project_chapter_no(project_id, chapter_no - 1)`，含 `chapter_no`、`title`、`summary`（摘要优先，否则正文前 500 字） |
| `arc_stage` | **优先** `outline.structure_json`，再 **fallback** `project.metadata_json`；兼容键见下节 |
| `next_hook_type` | `project.metadata_json`；兼容键见下节 |

### `arc_stage` 兼容键（优先级自上而下）

在 `structure_json` 与 `metadata_json` 中均按同一顺序查找，**先命中大纲结构、再命中项目元数据**：

1. `current_arc_stage`（推荐）
2. `arc_stage`
3. `story_arc_stage`
4. `narrative_arc_stage`
5. `arc_phase`

仅接受非空字符串或简单标量（数字/布尔会转为字符串）；**忽略** `dict` / `list`，避免误用嵌套对象。

### `next_hook_type` 兼容键（优先级自上而下）

仅在 `metadata_json` 中查找：

1. `next_hook_type`（推荐）
2. `next_hook`
3. `chapter_hook_type`
4. `hook_type`

## `projects.metadata_json` 写入建议

| 键 | 用途 |
|----|------|
| `current_arc_stage` | 卷内叙事阶段标签（与 `plot_context.arc_stage` 对齐） |
| `next_hook_type` | 本章或下章钩子类型提示 |
| `current_arc_brief` | 当前弧光一句/一段简述（进入 `project.metadata_json` 白名单） |
| `current_chapter_position_brief` | 当前章节在全书/卷中的位置简述 |
| `series_brief` | 系列级设定简述 |

键名可扩展：若需新增阶段/钩子字段，请同步更新 `service.py` 中 `_PLOT_ARC_STAGE_KEYS` / `_PLOT_NEXT_HOOK_KEYS` 并补充本文档。

## 审计日志

当 plot 载荷含非空 `retrieval` 视图时，可能记录 `event: plot_agent_retrieval_single_bundle`（含 `retrieval_chars`），便于体积审计。

## 相关文件

- `packages/workflows/orchestration/prompt_payload_types.py` — `ProjectProfile` / `OutlineProfile` / `RetrievalViewSpec.gap_treatment`
- `packages/workflows/orchestration/step_input_specs.py` — `plot_agent` 的 `STEP_INPUT_SPECS`
- `packages/workflows/orchestration/prompt_payload_assembler.py` — `outline` / `retrieval` / `project` 投影
- `packages/workflows/orchestration/service.py` — `plot_context`、弧光/钩子解析、无 `retrieval_summary`
- `apps/agents/plot_agent/prompt.md` — 对模型的输入说明与约束
