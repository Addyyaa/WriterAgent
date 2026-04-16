# 二档生成步骤：按需细节检索工具对照

摘要层由 `build_story_assets_from_context` 与 `PromptPayloadAssembler` 提供；需原文/全量档案时由工具拉取（勿在 prompt 中堆全库）。

| 能力 | 典型入口 | 参数要点 | 代码入口 |
|------|----------|----------|----------|
| 单条实体（角色/世界/时间线/伏笔） | 一致性审查 fetch / 本地工具 | `scope` + `entity_id`(UUID) | `SQLAlchemyStoryContextProvider.fetch_evidence_entity` |
| 章节正文/列表 | 章节工具 | `chapter_id` / `project_id` + `chapter_no` | `packages/tools/chapter_tools/` |
| 角色库存/上下文 | 角色工具 | `character_id`、`project_id` | `packages/tools/character_tools/` |
| 向量/记忆检索 | 记忆工具 | `query`、`top_k`、`project_id` | `packages/tools/retrieval_tools/` |
| 编排 BFF 本地数据 | `local_data_tools` 目录 | 见 `apps/agents/_shared/local_data_tools_catalog.json` | `packages/tools/system_tools/local_data_tools_dispatch.py` |

一档审查步骤默认启用 `WRITER_CONSISTENCY_REVIEW_STRICT_ENTITY_FETCH`：fetch 仅允许已出现在 `review_context` / `review_evidence_pack` 的 id。
