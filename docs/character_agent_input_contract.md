# character_agent / character_alignment 输入与模式合同

## 模式

| 模式 | `character_mode` / `strategy_mode` | 适用阶段 | 正文要求 |
|------|-------------------------------------|----------|----------|
| guardrails | `guardrails` 或 `planning`（归一为 guardrails） | 默认 DAG：`plot_alignment` → `character_alignment` → `writer_draft` | 不要求；不得做台词审计 |
| audit | `audit` | 成稿或草稿已存在之后（二次 run / 手工注入） | 须具备 `audit_chapter_text`、run 级 `audit_chapter_text`，或 DB 中当前 `chapter_no` 对应章节已有 `content` |

若请求 `audit` 但无任何正文证据，编排会**降级**为 `guardrails` 并打日志 `character_audit_degraded_no_chapter_text`。

## 步骤 `input_json` 约定

- `character_mode`：`guardrails` | `audit`。创建 `character_alignment` 步骤时默认写入 `guardrails`。
- `focus_character_id`：可选；缺省时尝试从 run `metadata_json` 或项目首个角色兜底。
- 审计专用：`audit_chapter_text`（字符串）、`audit_dialogue_snippets`（字符串列表）。

## Prompt 载荷（节选）

- `role_profile`：目标角色专属画像（非全剧 `character_arcs` + 全局 facts）。
- `recent_character_background`：`premise_excerpt`（截断）、`outline_hook`、`prior_events`。
- `Current_Chapter`：
  - 共有：`chapter_no`、`target_words`、`writing_goal`、`chapter_plan`、`beats_excerpt`、`confirmed_character_evidence`、`unresolved_gaps`。
  - 仅 audit：`chapter_text`、`dialogue_snippets`。

## 编排与依赖

- `character_alignment` 依赖 `plot_alignment`，以便注入 `chapter_plan`。
- System prompt 文件：`prompt_guardrails.md` / `prompt_audit.md`（`prompt.md` 为占位说明）。

## Writer 依赖

- `writer_draft` 仍从 `character_alignment` 视图读取 `motivation_analysis`、`tone_audit`、`constraints`（见 `step_input_specs`）。guardrails 下 `tone_audit` 为占位（`is_consistent=true`，理由/示例为空）。
