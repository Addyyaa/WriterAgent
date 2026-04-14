## 本地数据工具（系统可执行，无需 API Token）

以下能力由服务端通过数据库与向量库直接查询提供。你在推理时若需要这些信息，应在输出中明确意图（例如在 `notes` 中说明要查的 **工具名** 与 **参数**），或由编排层代为调用对应工具类。

| 工具名 | 作用 | 典型使用时机 |
|--------|------|----------------|
| `list_project_chapters` | 获取章节列表（仅标题与概述/摘要） | 需要章节目录、摘要、避免重复或对齐章节号 |
| `get_character_inventory` | 获取角色当前物品（章内快照优先） | 涉及道具、背包、消耗、财富与一致性 |
| `search_project_memory_vectors` | 向量语义检索项目记忆 | 需要前文证据、设定、伏笔与情节检索 |
| `get_chapter_content` | 读取章节正文（按 id 或标题） | 续写、引用、对比、修订某一章 |

参数说明：均需有效 `project_id`；`get_chapter_content` 须提供 `chapter_id` 或 `chapter_title` 之一；`get_character_inventory` 建议提供 `chapter_no` 以使用本章物品快照。
