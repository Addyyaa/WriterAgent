# character_agent

运行时由编排按 `character_mode` 注入 **`prompt_guardrails.md`**（生成前护栏）或 **`prompt_audit.md`**（生成后审计）。  
本文件保留以满足 AgentRegistry 加载约定；**请勿依赖本文件正文**作为唯一指令源。

默认章节链路使用 **guardrails**；仅当步骤/请求提供可审计的章节正文（`audit_chapter_text` 或已落库的同章 `content`）且 `character_mode=strategy_mode=audit` 时进入 **audit**。
