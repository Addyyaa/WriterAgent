# Writer Agent — 提示词路由（维护者说明）

本文件用于 **AgentRegistry** 加载与校验；**运行时系统提示**按步骤覆盖，模型不应依赖本节做任务理解。

- **草稿**（`chapter_generation` / `writer_draft`）：运行时注入 [`prompt_draft.md`](prompt_draft.md)（+ 共享 `local_data_tools`），契约见 `output_schema_draft.json`（若存在）。
- **修订**（`revision` / `writer_revision`）：运行时注入 [`prompt_revision.md`](prompt_revision.md)（+ 共享 `local_data_tools`），输出契约见 `output_schema.json` / 注册表解析结果。
- **其它 writer 步骤**：遵循当步 `output_schema` 与输入 JSON。
