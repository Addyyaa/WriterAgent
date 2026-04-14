#!/usr/bin/env python3
"""
本地数据四工具端到端：先写入可验证的 DB/向量数据，再指示 LLM 按工具拉取并复述，最后写日志并做关键词校验。

依赖：DATABASE_URL、WRITER_LLM_API_KEY（及 WRITER_LLM_BASE_URL / WRITER_LLM_MODEL 等）。

用法：
  ./venv/bin/python scripts/verify_local_data_tools_e2e_llm.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx

# 保证可从仓库根导入 packages
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from packages.llm.text_generation.runtime_config import TextGenerationRuntimeConfig
from packages.memory.long_term.search.search_service import MemorySearchService
from packages.memory.project_memory.project_memory_service import ProjectMemoryService
from packages.storage.postgres.repositories.character_repository import CharacterRepository
from packages.storage.postgres.repositories.chapter_repository import ChapterRepository
from packages.storage.postgres.repositories.memory_repository import MemoryChunkRepository
from packages.storage.postgres.repositories.project_repository import ProjectRepository
from packages.storage.postgres.session import create_session_factory
from packages.tools.system_tools.local_data_tools_dispatch import (
    LOCAL_DATA_TOOLS_OPENAI,
    execute_local_data_tool,
    parse_tool_arguments,
)
from scripts._chapter_workflow_support import DeterministicEmbeddingProvider

DEMO_PROJECT_TITLE = "LOCAL_TOOLS_E2E_DEMO"
# 以下短语用于日志与程序断言；勿随意改动，否则校验失败。
MARKER_CHAPTER_TITLE = "密室序章"
MARKER_CHAPTER_BODY = "橡木门后是向下十三级台阶"
MARKER_INVENTORY = "星火棱镜-7"
MARKER_MEMORY = "可验证记忆短语_AlphaBravo"


def _chat_url(base: str) -> str:
    return f"{str(base).rstrip('/')}/chat/completions"


def _remove_demo_project_if_exists(db) -> None:
    prepo = ProjectRepository(db)
    for p in prepo.list_all():
        if str(getattr(p, "title", "") or "").strip() == DEMO_PROJECT_TITLE:
            prepo.delete(p.id)
            break


def _seed_demo(db) -> dict[str, Any]:
    """写入项目、角色、章节、记忆块；返回 ground_truth 摘要。"""
    _remove_demo_project_if_exists(db)
    prepo = ProjectRepository(db)
    project = prepo.create(
        title=DEMO_PROJECT_TITLE,
        genre="e2e-demo",
        premise="用于本地工具链路验证的短项目。",
    )
    pid = project.id
    char_repo = CharacterRepository(db)
    character = char_repo.create(
        project_id=pid,
        name="演示角色甲",
        inventory_json={"items": [{"name": MARKER_INVENTORY, "qty": 1}]},
    )
    chap_repo = ChapterRepository(db)
    chapter = chap_repo.create(
        project_id=pid,
        title=MARKER_CHAPTER_TITLE,
        content=f"{MARKER_CHAPTER_BODY}。此处为可验证正文。",
    )
    chap_repo.update_content(
        chapter.id,
        chapter.content or "",
        summary="摘要：主角接近地下入口（E2E 种子）。",
    )
    embedder = DeterministicEmbeddingProvider()
    memory_text = (
        f"世界观设定（种子）：方舟塔纪元。关键锚点 {MARKER_MEMORY}仅应出现在本条记忆中。"
    )
    vec = embedder.embed_query(memory_text)
    mem_repo = MemoryChunkRepository(db)
    mem_repo.create_chunks(
        pid,
        [
            {
                "source_type": "world",
                "source_id": None,
                "chunk_type": "note",
                "text": memory_text,
                "embedding": vec,
                "embedding_status": "done",
                "metadata_json": {"seed": "local_tools_e2e"},
            }
        ],
    )
    search = MemorySearchService(embedding_provider=embedder, memory_repo=mem_repo)
    pms = ProjectMemoryService(long_term_search=search)
    return {
        "project_id": str(pid),
        "character_id": str(character.id),
        "chapter_id": str(chapter.id),
        "chapter_title": MARKER_CHAPTER_TITLE,
        "markers": {
            "chapter_title": MARKER_CHAPTER_TITLE,
            "chapter_body_snippet": MARKER_CHAPTER_BODY,
            "inventory": MARKER_INVENTORY,
            "memory": MARKER_MEMORY,
        },
        "project_memory_service": pms,
    }


def _ground_truth_tool_runs(db, ctx: dict[str, Any]) -> dict[str, Any]:
    """不经过 LLM，直接跑四轮工具，供日志对照。"""
    pms = ctx["project_memory_service"]
    pid = ctx["project_id"]
    cid = ctx["character_id"]
    out: dict[str, Any] = {}
    out["list_project_chapters"] = execute_local_data_tool(
        name="list_project_chapters",
        arguments={"project_id": pid},
        db=db,
        project_memory_service=pms,
    )
    out["get_character_inventory"] = execute_local_data_tool(
        name="get_character_inventory",
        arguments={"project_id": pid, "character_id": cid, "chapter_no": 1},
        db=db,
        project_memory_service=pms,
    )
    out["search_project_memory_vectors"] = execute_local_data_tool(
        name="search_project_memory_vectors",
        arguments={"project_id": pid, "query": "AlphaBravo", "top_k": 5},
        db=db,
        project_memory_service=pms,
    )
    out["get_chapter_content"] = execute_local_data_tool(
        name="get_chapter_content",
        arguments={"project_id": pid, "chapter_title": MARKER_CHAPTER_TITLE},
        db=db,
        project_memory_service=pms,
    )
    return out


def _run_llm_tool_loop(
    *,
    cfg: TextGenerationRuntimeConfig,
    system_prompt: str,
    user_prompt: str,
    db: Any,
    project_memory_service: ProjectMemoryService,
) -> tuple[list[dict[str, Any]], str | None, float]:
    """多轮 Chat Completions，直到模型不再返回 tool_calls。"""
    url = _chat_url(cfg.base_url)
    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
    }
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    transcript: list[dict[str, Any]] = []
    total_ms = 0.0
    final_text: str | None = None
    for round_idx in range(12):
        payload = {
            "model": cfg.model,
            "messages": messages,
            "temperature": 0.2,
            "tools": LOCAL_DATA_TOOLS_OPENAI,
            "tool_choice": "auto",
        }
        t0 = perf_counter()
        resp = httpx.post(url, headers=headers, json=payload, timeout=cfg.timeout_seconds)
        total_ms += (perf_counter() - t0) * 1000.0
        resp.raise_for_status()
        body = resp.json()
        msg = dict(body.get("choices", [{}])[0].get("message") or {})
        tool_calls = list(msg.get("tool_calls") or [])
        transcript.append(
            {
                "round": round_idx,
                "usage": body.get("usage"),
                "assistant": {
                    "content": msg.get("content"),
                    "tool_calls": tool_calls,
                },
            }
        )
        if not tool_calls:
            c = msg.get("content")
            final_text = c.strip() if isinstance(c, str) else str(c or "")
            break
        messages.append(
            {
                "role": "assistant",
                "content": msg.get("content") or "",
                "tool_calls": tool_calls,
            }
        )
        for call in tool_calls:
            cdict = dict(call or {})
            fn = dict(cdict.get("function") or {})
            name = str(fn.get("name") or "").strip()
            args = parse_tool_arguments(str(fn.get("arguments") or "{}"))
            result = execute_local_data_tool(
                name=name,
                arguments=args,
                db=db,
                project_memory_service=project_memory_service,
            )
            transcript.append(
                {
                    "round": round_idx,
                    "tool_result": {"name": name, "arguments": args, "result": result},
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(cdict.get("id") or ""),
                    "content": json.dumps(result, ensure_ascii=False)[:120_000],
                }
            )
    return transcript, final_text, total_ms


def _verify_llm_report(text: str, markers: dict[str, str]) -> dict[str, Any]:
    """检查模型最终中文报告是否提到各锚点（宽松包含即可）。"""
    lower = text.lower()
    checks = {
        "chapter_title": markers["chapter_title"] in text,
        "chapter_body": markers["chapter_body_snippet"] in text,
        "inventory": markers["inventory"] in text,
        "memory": markers["memory"] in text or "alphabravo" in lower,
    }
    return {"per_marker": checks, "all_ok": all(checks.values())}


def main() -> int:
    cfg = TextGenerationRuntimeConfig.from_env()
    if not str(cfg.api_key or "").strip():
        print("错误：未配置 WRITER_LLM_API_KEY", file=sys.stderr)
        return 2

    factory = create_session_factory()
    db = factory()
    log_path = _REPO_ROOT / "data" / "local_data_tools_e2e.log"
    worker_path = _REPO_ROOT / "data" / "worker.log"
    _REPO_ROOT.joinpath("data").mkdir(parents=True, exist_ok=True)

    try:
        ctx = _seed_demo(db)
        markers = ctx["markers"]
        ground = _ground_truth_tool_runs(db, ctx)
        pms = ctx["project_memory_service"]

        system_prompt = (
            "你是测试协作助手，必须使用用户给出的 UUID 与工具定义从数据库拉取事实，禁止编造。"
            "请按需多次调用工具，直到掌握：章节列表、角色物品、向量记忆片段、章节正文。"
            "工具全部执行完后，用中文写「核对报告」，四个小节分别对应："
            "①章节列表是否出现指定标题；②物品是否含指定道具名；③记忆检索是否命中指定短语；④章节正文是否含指定句子。"
            "每节开头用「是」或「否」，并引用工具返回中的原词短语。"
        )
        user_prompt = (
            f"project_id={ctx['project_id']}\n"
            f"character_id={ctx['character_id']}\n"
            f"章节标题（get_chapter_content 用 chapter_title）={MARKER_CHAPTER_TITLE}\n"
            f"向量检索 query 请使用包含「AlphaBravo」或「可验证记忆短语」的自然语句。\n\n"
            f"必须验证的锚点（须在报告中逐条体现）：\n"
            f"- 章节标题含：{MARKER_CHAPTER_TITLE}\n"
            f"- 正文含句子：{MARKER_CHAPTER_BODY}\n"
            f"- 物品名：{MARKER_INVENTORY}\n"
            f"- 记忆短语：{MARKER_MEMORY}\n"
        )

        transcript, final_text, llm_ms = _run_llm_tool_loop(
            cfg=cfg,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            db=db,
            project_memory_service=pms,
        )
        verification = _verify_llm_report(final_text or "", markers)

        record = {
            "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "task": "local_data_tools_e2e_llm",
            "model": cfg.model,
            "expected_markers": markers,
            "ground_truth_tools": ground,
            "llm_total_ms": round(llm_ms, 2),
            "transcript_rounds": transcript,
            "llm_final_text": final_text,
            "verification": verification,
        }
        line = json.dumps(record, ensure_ascii=False, indent=2)
        with log_path.open("a", encoding="utf-8") as f:
            f.write("=== LOCAL_DATA_TOOLS_E2E VERIFY START ===\n")
            f.write(line + "\n")
            f.write("=== LOCAL_DATA_TOOLS_E2E VERIFY END ===\n")

        with worker_path.open("a", encoding="utf-8") as wf:
            wf.write("=== LOCAL_DATA_TOOLS_E2E SUMMARY ===\n")
            wf.write(
                json.dumps(
                    {
                        "timestamp_utc": record["timestamp_utc"],
                        "verification": verification,
                        "project_id": ctx["project_id"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

        print(line)
        if not verification["all_ok"]:
            print(
                "\n校验未全部通过：模型最终报告未包含全部锚点。详见 per_marker。",
                file=sys.stderr,
            )
            return 1
        print("\n校验通过：最终报告包含全部锚点。")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
