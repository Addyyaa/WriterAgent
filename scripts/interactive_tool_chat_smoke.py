#!/usr/bin/env python3
"""交互式验证 LLM function calling（tools / tool_calls）。

默认挂载与生产一致的「本地数据工具」：
  list_project_chapters、get_character_inventory、search_project_memory_vectors、
  get_chapter_content（定义见 packages/tools/system_tools/local_data_tools_dispatch.py）。

依赖环境变量：
  WRITER_LLM_BASE_URL、WRITER_LLM_API_KEY、WRITER_LLM_MODEL
  数据库：与主应用相同的 PostgreSQL 连接（见 packages/storage/postgres/session）

用法：
  ./venv/bin/python scripts/interactive_tool_chat_smoke.py
  ./venv/bin/python scripts/interactive_tool_chat_smoke.py --project-id <UUID>
  ./venv/bin/python scripts/interactive_tool_chat_smoke.py --demo   # 不连库，仅假工具

命令：
  /quit /exit   退出
  /reset        清空对话
  /tools        打印当前 tools JSON
  /help         帮助
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

from packages.llm.text_generation.factory import create_text_generation_provider
from packages.llm.text_generation.openai_compatible import OpenAICompatibleTextProvider
from packages.llm.text_generation.runtime_config import TextGenerationRuntimeConfig
from packages.memory.long_term.search.search_service import MemorySearchService
from packages.memory.project_memory.project_memory_service import ProjectMemoryService
from packages.retrieval.chunking.simple_text_chunker import SimpleTextChunker
from packages.storage.postgres.repositories.chapter_repository import ChapterRepository
from packages.storage.postgres.repositories.character_repository import CharacterRepository
from packages.storage.postgres.repositories.memory_fact_repository import MemoryFactRepository
from packages.storage.postgres.repositories.memory_repository import MemoryChunkRepository
from packages.storage.postgres.repositories.project_repository import ProjectRepository
from packages.storage.postgres.session import create_session_factory
from packages.tools.system_tools.local_data_tools_dispatch import (
    LOCAL_DATA_TOOLS_OPENAI,
    execute_local_data_tool,
)


def _demo_tools_schema() -> list[dict[str, Any]]:
    """无数据库时的占位工具（仅测 LLM 协议）。"""
    return [
        {
            "type": "function",
            "function": {
                "name": "get_fake_fact",
                "description": "演示：根据主题返回一条虚构事实（不访问外网）。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "description": "主题"},
                    },
                    "required": ["topic"],
                    "additionalProperties": False,
                },
            },
        },
    ]


def _run_demo_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "get_fake_fact":
        topic = str(arguments.get("topic") or "").strip() or "未命名"
        return {"ok": True, "topic": topic, "fact": f"【演示】关于「{topic}」的占位事实。"}
    return {"ok": False, "error": f"未知工具: {name}"}


def _build_project_memory_service(db: Any) -> ProjectMemoryService:
    from packages.memory.long_term.ingestion.ingestion_service import MemoryIngestionService
    from scripts._chapter_workflow_support import DeterministicEmbeddingProvider

    embedding_provider = DeterministicEmbeddingProvider()
    memory_repo = MemoryChunkRepository(db)
    memory_fact_repo = MemoryFactRepository(db)
    MemoryIngestionService(
        chunker=SimpleTextChunker(chunk_size=500, chunk_overlap=80),
        embedding_provider=embedding_provider,
        memory_repo=memory_repo,
        memory_fact_repo=memory_fact_repo,
        embedding_batch_size=8,
        replace_existing_by_default=True,
    )
    search_service = MemorySearchService(
        embedding_provider=embedding_provider,
        memory_repo=memory_repo,
    )
    return ProjectMemoryService(long_term_search=search_service)


def _resolve_default_project_context(db: Any, project_id: str | None) -> dict[str, Any] | None:
    prepo = ProjectRepository(db)
    if project_id and str(project_id).strip():
        row = prepo.get(project_id)
        if row is None:
            print(f"[错误] 找不到 project_id={project_id}", file=sys.stderr)
            return None
        pid = row.id
    else:
        projects = prepo.list_all()
        if not projects:
            return None
        pid = projects[0].id
    chars = CharacterRepository(db).list_by_project(project_id=pid, limit=1)
    chapters = ChapterRepository(db).list_by_project(pid)
    cid = chars[0].id if chars else None
    chap = chapters[0] if chapters else None
    return {
        "project_id": str(pid),
        "character_id": str(cid) if cid else "",
        "chapter_id": str(getattr(chap, "id", "") or "") if chap else "",
        "chapter_title": str(getattr(chap, "title", "") or "") if chap else "",
    }


def _system_prompt(*, demo: bool, ctx: dict[str, Any] | None) -> str:
    if demo:
        return (
            "你是助手。用户会提问；需要演示数据时请调用 get_fake_fact。"
            "不要编造工具未返回的内容。"
        )
    lines = [
        "你是写作/审查助手，可使用下列本地数据工具查询真实库表（必须传入正确 UUID）：",
        "- list_project_chapters(project_id)",
        "- get_character_inventory(project_id, character_id, chapter_no 可选)",
        "- search_project_memory_vectors(project_id, query, top_k/token_budget 可选)",
        "- get_chapter_content(project_id, chapter_id 或 chapter_title 二选一之一)",
        "不要编造工具未返回的数据；章节正文可能很长，回答时摘要即可。",
    ]
    if ctx:
        lines.append(f"默认 project_id（用户未指定时可使用）: {ctx['project_id']}")
        if ctx.get("character_id"):
            lines.append(f"示例 character_id: {ctx['character_id']}")
        if ctx.get("chapter_title"):
            lines.append(f"示例 chapter_title: {ctx['chapter_title']}")
        if ctx.get("chapter_id"):
            lines.append(f"示例 chapter_id: {ctx['chapter_id']}")
    return "\n".join(lines)


def _truncate_tool_json(payload: dict[str, Any], max_chars: int = 24000) -> str:
    raw = json.dumps(payload, ensure_ascii=False)
    if len(raw) <= max_chars:
        return raw
    return raw[: max_chars - 20] + "…【控制台截断】"


def _chat_round(
    *,
    provider: OpenAICompatibleTextProvider,
    cfg: TextGenerationRuntimeConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_choice: str | dict[str, Any],
    max_tokens: int,
    max_tool_rounds: int,
    run_tool: Callable[[str, dict[str, Any]], dict[str, Any]],
) -> None:
    for round_i in range(max_tool_rounds):
        body = provider.chat_completions(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=0.35,
            max_tokens=max_tokens,
            read_timeout=cfg.timeout_seconds,
        )
        try:
            choice0 = (body.get("choices") or [{}])[0]
            msg = dict(choice0.get("message") or {})
        except Exception as exc:
            print("[错误] 响应无 choices/message:", exc, file=sys.stderr)
            print(json.dumps(body, ensure_ascii=False, indent=2)[:4000], file=sys.stderr)
            return

        finish = choice0.get("finish_reason")
        print(f"[调试] finish_reason={finish!r} round={round_i}")

        tool_calls = list(msg.get("tool_calls") or [])
        if tool_calls:
            messages.append(msg)
            print(f"[模型] 发起 {len(tool_calls)} 个 tool_calls")
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                fn = dict(tc.get("function") or {})
                tname = str(fn.get("name") or "").strip()
                raw_args = str(fn.get("arguments") or "{}").strip()
                try:
                    args = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                print(f"  · 调用 {tname}({raw_args[:200]}{'…' if len(raw_args) > 200 else ''})")
                result = run_tool(tname, args)
                tid = str(tc.get("id") or "").strip() or "call_unknown"
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tid,
                        "content": _truncate_tool_json(result),
                    }
                )
            continue

        content = msg.get("content")
        text = ""
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
            text = "\n".join(parts).strip()
        messages.append(msg)
        if text:
            print(f"\n助手：\n{text}\n")
        else:
            print("\n[警告] 助手消息无文本 content，原始 message：")
            print(json.dumps(msg, ensure_ascii=False, indent=2)[:3000])
        return

    print(f"[错误] 超过 max_tool_rounds={max_tool_rounds}，停止以防死循环。", file=sys.stderr)


def _supports_forced_tool_choice(provider: OpenAICompatibleTextProvider) -> bool:
    return bool(provider._forced_function_tool_choice_supported())  # noqa: SLF001


def main() -> int:
    parser = argparse.ArgumentParser(description="交互式 LLM 工具调用（项目本地数据工具）")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="不连接数据库，仅注册 get_fake_fact 演示工具",
    )
    parser.add_argument(
        "--project-id",
        default="",
        help="默认项目 UUID；省略则取库中第一个项目",
    )
    parser.add_argument(
        "--tool-choice",
        choices=["auto", "required"],
        default="auto",
        help="required：强制调用第一个工具（部分网关不支持）",
    )
    parser.add_argument(
        "--max-tool-rounds",
        type=int,
        default=8,
    )
    args = parser.parse_args()

    cfg = TextGenerationRuntimeConfig.from_env()
    if not (cfg.api_key or "").strip():
        print("未设置 WRITER_LLM_API_KEY，无法请求模型。", file=sys.stderr)
        return 2

    provider = create_text_generation_provider(cfg)
    if not isinstance(provider, OpenAICompatibleTextProvider):
        print("当前 Provider 非 OpenAICompatibleTextProvider。", file=sys.stderr)
        return 2

    db: Any = None
    pms: ProjectMemoryService | None = None
    ctx: dict[str, Any] | None = None

    if args.demo:
        tools = _demo_tools_schema()

        def run_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            return _run_demo_tool(name, arguments)

    else:
        tools = list(LOCAL_DATA_TOOLS_OPENAI)
        factory = create_session_factory()
        db = factory()
        ctx = _resolve_default_project_context(db, args.project_id or None)
        if ctx is None:
            print("数据库中无项目：请创建项目后再试，或使用 --demo。", file=sys.stderr)
            db.close()
            return 2
        pms = _build_project_memory_service(db)

        def run_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            assert db is not None and pms is not None
            return execute_local_data_tool(
                name=name,
                arguments=arguments,
                db=db,
                project_memory_service=pms,
            )

    if args.tool_choice == "required":
        if not _supports_forced_tool_choice(provider):
            print("[警告] 当前网关不支持强制 tool_choice，将使用 auto。", file=sys.stderr)
            tool_choice: str | dict[str, Any] = "auto"
        else:
            tool_choice = {
                "type": "function",
                "function": {"name": tools[0]["function"]["name"]},
            }
    else:
        tool_choice = "auto"

    max_tokens = int(cfg.max_output_tokens or 2048)
    max_tokens = max(256, min(max_tokens, 8192))

    sys_msg = _system_prompt(demo=bool(args.demo), ctx=ctx)
    messages: list[dict[str, Any]] = [{"role": "system", "content": sys_msg}]

    print("交互式工具烟测 | 模型:", cfg.model, "|", cfg.base_url)
    if args.demo:
        print("模式: --demo（假工具）\n")
    else:
        print("模式: 项目本地数据工具 | 默认 project_id:", ctx["project_id"] if ctx else "?")
        print("示例：「列出该项目章节」「检索记忆：主角身世」「读某一章正文摘要」\n")

    try:
        while True:
            try:
                line = input("你：").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n再见。")
                return 0

            if not line:
                continue
            if line in {"/quit", "/exit", "quit", "exit"}:
                print("再见。")
                return 0
            if line == "/reset":
                messages = [{"role": "system", "content": sys_msg}]
                print("[已清空对话]\n")
                continue
            if line == "/tools":
                print(json.dumps(tools, ensure_ascii=False, indent=2))
                continue
            if line == "/help":
                print(__doc__)
                continue

            messages.append({"role": "user", "content": line})
            _chat_round(
                provider=provider,
                cfg=cfg,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                max_tokens=max_tokens,
                max_tool_rounds=max(1, int(args.max_tool_rounds)),
                run_tool=run_tool,
            )
    finally:
        if db is not None:
            db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
