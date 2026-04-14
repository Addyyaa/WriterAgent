from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx
import pytest

from packages.llm.text_generation.runtime_config import TextGenerationRuntimeConfig
from packages.memory.long_term.ingestion.ingestion_service import MemoryIngestionService
from packages.memory.long_term.search.search_service import MemorySearchService
from packages.memory.project_memory.project_memory_service import ProjectMemoryService
from packages.retrieval.chunking.simple_text_chunker import SimpleTextChunker
from packages.schemas import SchemaRegistry
from packages.skills import SkillRegistry
from packages.storage.postgres.repositories.character_repository import CharacterRepository
from packages.storage.postgres.repositories.chapter_repository import ChapterRepository
from packages.storage.postgres.repositories.memory_fact_repository import MemoryFactRepository
from packages.storage.postgres.repositories.memory_repository import MemoryChunkRepository
from packages.storage.postgres.repositories.project_repository import ProjectRepository
from packages.storage.postgres.session import create_session_factory
from packages.tools.system_tools.local_data_tools_dispatch import (
    LOCAL_DATA_TOOLS_OPENAI,
    execute_local_data_tool,
    parse_tool_arguments,
)
from packages.workflows.orchestration.agent_registry import AgentRegistry
from scripts._chapter_workflow_support import DeterministicEmbeddingProvider


def _chat_completions_url(base_url: str) -> str:
    return f"{str(base_url).rstrip('/')}/chat/completions"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _truncate_tool_result_for_log(payload: dict[str, Any], *, chapter_content_max: int = 6000) -> dict[str, Any]:
    """日志用：缩小章节正文等长字段，避免单条日志撑爆编辑器。"""
    try:
        raw = json.dumps(payload, ensure_ascii=False)
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {"_note": "无法序列化工具结果，已省略", "repr": str(payload)[:2000]}
    if not isinstance(data, dict):
        return data  # type: ignore[return-value]
    ch = data.get("chapter")
    if isinstance(ch, dict) and "content" in ch:
        text = str(ch.get("content") or "")
        if len(text) > chapter_content_max:
            ch = dict(ch)
            ch["content"] = text[:chapter_content_max] + f"... [日志截断，原长 {len(text)} 字符]"
            out = dict(data)
            out["chapter"] = ch
            return out
    items = data.get("items")
    if isinstance(items, list) and len(items) > 50:
        out = dict(data)
        out["items"] = items[:50]
        out["_items_truncated"] = len(items) - 50
        return out
    return data


def _append_local_data_tools_test_logs(
    *,
    repo_root: Path,
    role_id: str,
    forced_tool: str,
    first_latency_ms: float,
    first_response_body: dict[str, Any],
    assistant_message_round1: dict[str, Any],
    tool_arguments: dict[str, Any],
    tool_result: dict[str, Any],
    second_latency_ms: float | None,
    assistant_summary_round2: str | None,
    second_error: str | None,
) -> None:
    """将 LLM 与工具链路写入 data/worker.log（完整 JSON）与 data/local_data_tools_llm.log（行摘要）。

    不写入 data/llm.log：该文件由应用内 writeragent.llm 日志器独占，避免格式混杂与时间线误解。
    """
    data_dir = repo_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    usage = first_response_body.get("usage")
    tool_for_file = _truncate_tool_result_for_log(tool_result)

    record = {
        "timestamp_utc": ts,
        "test": "local_data_tools_agent_llm",
        "role_id": role_id,
        "forced_tool": forced_tool,
        "round1_latency_ms": round(first_latency_ms, 2),
        "round1_usage": usage,
        "round1_assistant_message": assistant_message_round1,
        "tool_arguments": tool_arguments,
        "tool_result_for_log": tool_for_file,
        "round2_latency_ms": round(second_latency_ms, 2) if second_latency_ms is not None else None,
        "round2_summary_zh": assistant_summary_round2,
        "round2_error": second_error,
    }
    worker_path = data_dir / "worker.log"
    tools_llm_path = data_dir / "local_data_tools_llm.log"
    json_block = json.dumps(record, ensure_ascii=False, indent=2)
    with worker_path.open("a", encoding="utf-8") as wf:
        wf.write("=== LOCAL_DATA_TOOLS_LLM_TEST START ===\n")
        wf.write(json_block + "\n")
        wf.write("=== LOCAL_DATA_TOOLS_LLM_TEST END ===\n")
    line = (
        f"{ts} [INFO] local_data_tools_test - role={role_id} tool={forced_tool} "
        f"r1_ms={first_latency_ms:.0f} r2_ms={second_latency_ms or 0:.0f} "
        f"summary_len={len(assistant_summary_round2 or '')}\n"
    )
    with tools_llm_path.open("a", encoding="utf-8") as lf:
        lf.write(line)
        if assistant_summary_round2:
            lf.write(
                f"{ts} [INFO] local_data_tools_test.summary - role={role_id} - "
                + (assistant_summary_round2.replace("\n", " ")[:2000])
                + "\n"
            )


def _build_project_memory_service(db):
    embedding_provider = DeterministicEmbeddingProvider()
    memory_repo = MemoryChunkRepository(db)
    memory_fact_repo = MemoryFactRepository(db)
    _ingestion = MemoryIngestionService(
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
    _ = _ingestion  # 保持与 worker 一致的可注入管线；本测试仅依赖 search。
    return ProjectMemoryService(long_term_search=search_service)


def _sample_project_context(db):
    """返回用于工具 smoke 的 id；无数据时返回 None。"""
    prepo = ProjectRepository(db)
    projects = prepo.list_all()
    if not projects:
        return None
    project = projects[0]
    pid = project.id
    chars = CharacterRepository(db).list_by_project(project_id=pid, limit=1)
    chapters = ChapterRepository(db).list_by_project(pid)
    cid = chars[0].id if chars else None
    chap = chapters[0] if chapters else None
    return {
        "project_id": str(pid),
        "character_id": str(cid) if cid else str(uuid.uuid4()),
        "chapter_title": str(getattr(chap, "title", "") or "") if chap else "",
        "chapter_id": str(getattr(chap, "id", "")) if chap else "",
        "has_character": cid is not None,
        "has_chapter": chap is not None,
    }


requires_llm = pytest.mark.skipif(
    not str(os.environ.get("WRITER_LLM_API_KEY", "")).strip(),
    reason="需要 WRITER_LLM_API_KEY 以调用真实 LLM",
)


@pytest.fixture(scope="module")
def agent_registry() -> AgentRegistry:
    root = _repo_root()
    schema_registry = SchemaRegistry(root / "packages/schemas")
    skill_registry = SkillRegistry(
        root=root / "packages/skills",
        schema_registry=schema_registry,
        strict=True,
        degrade_mode=False,
    )
    return AgentRegistry(
        root=root / "apps/agents",
        schema_registry=schema_registry,
        skill_registry=skill_registry,
        strict=True,
        degrade_mode=False,
    )


def test_agent_profiles_include_local_tools_markdown(agent_registry: AgentRegistry) -> None:
    """各 agent 的 prompt 由 Registry 拼接 _shared/local_data_tools.md，模型应能看到工具表。"""
    marker = "list_project_chapters"
    for role_id in agent_registry.list_role_ids():
        profile = agent_registry.get(role_id)
        assert profile is not None
        assert marker in profile.prompt, f"{role_id} 缺少本地工具说明片段"


def test_execute_local_data_tools_against_db() -> None:
    """不经过 LLM，直接调用调度函数，验证数据库与向量检索链路可执行。"""
    factory = create_session_factory()
    db = factory()
    try:
        ctx = _sample_project_context(db)
        if ctx is None:
            pytest.skip("数据库中无项目，跳过工具执行 smoke")
        pms = _build_project_memory_service(db)
        pid = ctx["project_id"]

        r0 = execute_local_data_tool(
            name="list_project_chapters",
            arguments={"project_id": pid},
            db=db,
            project_memory_service=pms,
        )
        assert "items" in r0 and "count" in r0

        r1 = execute_local_data_tool(
            name="get_character_inventory",
            arguments={
                "project_id": pid,
                "character_id": ctx["character_id"],
                "chapter_no": 1,
            },
            db=db,
            project_memory_service=pms,
        )
        assert "found" in r1
        if ctx["has_character"]:
            assert r1.get("found") is True
        else:
            assert r1.get("found") is False

        r2 = execute_local_data_tool(
            name="search_project_memory_vectors",
            arguments={"project_id": pid, "query": "smoke", "top_k": 3},
            db=db,
            project_memory_service=pms,
        )
        assert "items" in r2

        args_content: dict = {"project_id": pid}
        if ctx["chapter_title"]:
            args_content["chapter_title"] = ctx["chapter_title"]
        elif ctx["chapter_id"]:
            args_content["chapter_id"] = ctx["chapter_id"]
        else:
            pytest.skip("无章节标题与 id，跳过 get_chapter_content")

        r3 = execute_local_data_tool(
            name="get_chapter_content",
            arguments=args_content,
            db=db,
            project_memory_service=pms,
        )
        assert "found" in r3
    finally:
        db.close()


@requires_llm
@pytest.mark.parametrize(
    "role_id,forced_tool",
    [
        ("planner_agent", "list_project_chapters"),
        ("character_agent", "get_character_inventory"),
        ("retrieval_agent", "search_project_memory_vectors"),
        ("world_agent", "search_project_memory_vectors"),
        ("plot_agent", "get_chapter_content"),
        ("style_agent", "search_project_memory_vectors"),
        ("writer_agent", "get_chapter_content"),
        ("consistency_agent", "get_chapter_content"),
    ],
)
def test_llm_forced_tool_call_per_agent_role(role_id: str, forced_tool: str, agent_registry: AgentRegistry) -> None:
    """
    使用与各 agent 一致的系统提示（含本地工具说明），并强制 tool_choice，
    验证厂商 API + 参数解析 + Python 工具执行全链路可用。
    """
    profile = agent_registry.get(role_id)
    assert profile is not None

    cfg = TextGenerationRuntimeConfig.from_env()
    factory = create_session_factory()
    db = factory()
    try:
        ctx = _sample_project_context(db)
        if ctx is None:
            pytest.skip("数据库中无项目")
        if forced_tool == "get_chapter_content" and not (ctx["chapter_title"] or ctx["chapter_id"]):
            pytest.skip("需要章节以测试 get_chapter_content")
        if forced_tool == "get_character_inventory" and not ctx["has_character"]:
            pytest.skip("需要角色以测试 get_character_inventory")

        pms = _build_project_memory_service(db)
        user_lines = [
            "仅用于工具参数（从下列键取值，勿改写 UUID）：",
            f"project_id={ctx['project_id']}",
            f"character_id={ctx['character_id']}",
            f"chapter_title={ctx['chapter_title'] or '第一章'}",
            "chapter_no=1",
            "query=项目设定",
            f"请调用工具 {forced_tool}，参数必填项一律从上面取值。",
        ]
        user_message = "\n".join(user_lines)

        payload = {
            "model": cfg.model,
            "messages": [
                {"role": "system", "content": profile.prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.1,
            "tools": LOCAL_DATA_TOOLS_OPENAI,
            "tool_choice": {"type": "function", "function": {"name": forced_tool}},
        }
        url = _chat_completions_url(cfg.base_url)
        headers = {
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
        }
        t0 = perf_counter()
        resp = httpx.post(url, headers=headers, json=payload, timeout=cfg.timeout_seconds)
        resp.raise_for_status()
        body = resp.json()
        first_ms = (perf_counter() - t0) * 1000.0
        msg = dict(body.get("choices", [{}])[0].get("message") or {})
        tool_calls = list(msg.get("tool_calls") or [])
        assert tool_calls, f"{role_id}: LLM 未返回 tool_calls"
        call0 = dict(tool_calls[0] or {})
        fn = dict(call0.get("function") or {})
        assert str(fn.get("name") or "").strip() == forced_tool
        args = parse_tool_arguments(str(fn.get("arguments") or "{}"))
        out = execute_local_data_tool(
            name=forced_tool,
            arguments=args,
            db=db,
            project_memory_service=pms,
        )
        assert isinstance(out, dict)
        if str(out.get("error") or "").strip():
            pytest.fail(f"工具执行失败: {out}")

        # 第二轮：把工具 JSON 回传模型，生成中文摘要（耗时更长，便于核对「模型读到的内容」）
        tool_content = json.dumps(out, ensure_ascii=False)
        max_tool_chars = 120_000
        if len(tool_content) > max_tool_chars:
            tool_content = tool_content[:max_tool_chars] + "\n…[工具 JSON 过长已截断以适配 API]"

        second_payload = {
            "model": cfg.model,
            "messages": [
                {"role": "system", "content": profile.prompt},
                {"role": "user", "content": user_message},
                {
                    "role": "assistant",
                    "content": msg.get("content") or "",
                    "tool_calls": tool_calls,
                },
                {
                    "role": "tool",
                    "tool_call_id": str(call0.get("id") or ""),
                    "content": tool_content,
                },
                {
                    "role": "user",
                    "content": (
                        "请严格根据上一条 role=tool 中的 JSON 作答，用中文写一段给作者看的摘要："
                        "列出工具返回的关键事实（条列或短段落均可），勿编造 JSON 中不存在的信息。"
                        "篇幅120～400 字。"
                    ),
                },
            ],
            "temperature": 0.3,
        }
        summary_text: str | None = None
        second_ms: float | None = None
        second_err: str | None = None
        t1 = perf_counter()
        try:
            resp2 = httpx.post(url, headers=headers, json=second_payload, timeout=cfg.timeout_seconds)
            resp2.raise_for_status()
            body2 = resp2.json()
            second_ms = (perf_counter() - t1) * 1000.0
            msg2 = dict(body2.get("choices", [{}])[0].get("message") or {})
            c2 = msg2.get("content")
            summary_text = c2.strip() if isinstance(c2, str) else str(c2 or "")
        except Exception as exc:  # noqa: BLE001 — 测试日志需记录失败原因
            second_ms = (perf_counter() - t1) * 1000.0
            second_err = str(exc)

        _append_local_data_tools_test_logs(
            repo_root=_repo_root(),
            role_id=role_id,
            forced_tool=forced_tool,
            first_latency_ms=first_ms,
            first_response_body=body,
            assistant_message_round1={
                "content": msg.get("content"),
                "tool_calls": tool_calls,
            },
            tool_arguments=args,
            tool_result=out,
            second_latency_ms=second_ms,
            assistant_summary_round2=summary_text,
            second_error=second_err,
        )
        if second_err:
            pytest.fail(f"第二轮 LLM（基于工具结果写摘要）失败: {second_err}")
        assert summary_text and len(summary_text) >= 10, f"{role_id}: 第二轮模型摘要过短"
    finally:
        db.close()
