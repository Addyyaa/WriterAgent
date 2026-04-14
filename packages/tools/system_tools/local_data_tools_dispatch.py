from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from packages.tools.chapter_tools.chapter_content_tool import ChapterContentTool
from packages.tools.chapter_tools.chapter_list_tool import ChapterListTool
from packages.tools.character_tools.inventory_tool import CharacterInventoryTool
from packages.tools.retrieval_tools.vector_memory_tool import ProjectVectorMemorySearchTool

if TYPE_CHECKING:
    from packages.memory.project_memory.project_memory_service import ProjectMemoryService

# 与 apps/agents/_shared/local_data_tools.md 中的工具名一致；供 Chat Completions `tools` 字段使用。
LOCAL_DATA_TOOLS_OPENAI: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_project_chapters",
            "description": "列出项目下章节，仅标题与概述（摘要），不含正文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "项目 UUID"},
                },
                "required": ["project_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_character_inventory",
            "description": "查询角色当前物品（本章快照优先，否则角色默认 inventory）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "character_id": {"type": "string"},
                    "chapter_no": {"type": "integer", "description": "可选，指定章号以使用本章快照"},
                },
                "required": ["project_id", "character_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_project_memory_vectors",
            "description": "在项目长期记忆向量库中做语义检索。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 64},
                    "token_budget": {"type": "integer", "minimum": 200},
                },
                "required": ["project_id", "query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_chapter_content",
            "description": "读取章节正文；可按 chapter_id 或 chapter_title（项目内标题）查询。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "chapter_id": {"type": "string", "description": "章节 UUID，与 chapter_title 二选一"},
                    "chapter_title": {"type": "string", "description": "章节标题，与 chapter_id 二选一"},
                },
                "required": ["project_id"],
                "additionalProperties": False,
            },
        },
    },
]


def parse_tool_arguments(raw: str | None) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    data = json.loads(text)
    return dict(data) if isinstance(data, dict) else {}


def execute_local_data_tool(
    *,
    name: str,
    arguments: dict[str, Any],
    db: Any,
    project_memory_service: ProjectMemoryService,
) -> dict[str, Any]:
    """根据 LLM 返回的 function name 与参数执行对应 Python 工具。"""
    key = str(name or "").strip()
    if key == "list_project_chapters":
        pid = arguments.get("project_id")
        if not pid:
            return {"error": "缺少 project_id"}
        return ChapterListTool(db).run(project_id=pid)
    if key == "get_character_inventory":
        pid = arguments.get("project_id")
        cid = arguments.get("character_id")
        if not pid or not cid:
            return {"error": "缺少 project_id 或 character_id"}
        ch_no = arguments.get("chapter_no")
        ch_int = int(ch_no) if ch_no is not None else None
        return CharacterInventoryTool(db).run(project_id=pid, character_id=cid, chapter_no=ch_int)
    if key == "search_project_memory_vectors":
        pid = arguments.get("project_id")
        query = str(arguments.get("query") or "").strip()
        if not pid or not query:
            return {"error": "缺少 project_id 或 query"}
        top_k = int(arguments.get("top_k", 8))
        token_budget = int(arguments.get("token_budget", 2000))
        return ProjectVectorMemorySearchTool(project_memory_service).run(
            project_id=pid,
            query=query,
            top_k=top_k,
            token_budget=token_budget,
        )
    if key == "get_chapter_content":
        pid = arguments.get("project_id")
        if not pid:
            return {"error": "缺少 project_id"}
        return ChapterContentTool(db).run(
            project_id=pid,
            chapter_id=arguments.get("chapter_id"),
            chapter_title=arguments.get("chapter_title"),
        )
    return {"error": f"未知工具: {key}"}
