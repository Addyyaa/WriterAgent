#!/usr/bin/env python3
"""调试验证：打印章节 writer 将发给 LLM 的 system + user 上下文，不调用模型。

用法（仓库根目录）：
  ./venv/bin/python scripts/debug_chapter_writer_context.py
  ./venv/bin/python scripts/debug_chapter_writer_context.py --orchestrated
  ./venv/bin/python scripts/debug_chapter_writer_context.py --no-registry
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

# 仓库根目录
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from packages.core.utils.chapter_metrics import chapter_word_count_allowed_range
from packages.schemas import SchemaRegistry
from packages.skills import SkillRegistry
from packages.workflows.chapter_generation.service import ChapterGenerationWorkflowService
from packages.workflows.orchestration.agent_registry import AgentRegistry


def _sample_orchestrator_raw_state() -> dict:
    """与单元测试一致的迷你编排快照，用于 writer_draft 分支。"""
    return {
        "outline_generation": {"title": "大纲", "content": "纲要", "structure_json": {"acts": []}},
        "plot_alignment": {
            "chapter_goal": "推进主线",
            "core_conflict": "信任危机",
            "narcotic_arc": [
                {
                    "phase": "起",
                    "plot_beat": "切入矛盾",
                    "conflict_level": 5,
                    "pacing_note": "紧",
                    "outcome": "升级",
                }
            ],
            "climax_twist": {"description": "反转", "impact": "高"},
        },
        "character_alignment": {
            "motivation_analysis": {"explicit": "求存", "implicit": "恐惧", "emotion_shift": "压抑"},
            "tone_audit": {"is_consistent": True},
            "constraints": {"must_do": ["不剧透"], "must_not": ["OOC"]},
        },
        "world_alignment": {
            "world_logic_summary": "低魔",
            "hard_constraints": [],
            "reusable_assets": {"locations": ["主城"], "factions": [], "items_concepts": []},
            "potential_conflicts": [],
        },
        "style_alignment": {
            "style_mission": "冷峻",
            "micro_constraints": {
                "sentence_structure": "短句",
                "vocabulary_level": "中",
                "forbidden_words": [],
            },
            "rhythm_strategy": {"pacing": "快", "instruction": "少铺陈"},
            "anti_drift_checks": [],
            "tonal_keywords": [],
        },
        "retrieval_context": {
            "view": {
                "writing_context_summary": {
                    "key_facts": ["事实A"],
                    "current_states": ["状态B"],
                }
            }
        },
    }


def _build_service(*, use_registry: bool) -> ChapterGenerationWorkflowService:
    """最小依赖：不连 DB、不调 LLM。"""
    from packages.llm.text_generation.base import TextGenerationProvider, TextGenerationRequest, TextGenerationResult

    class _NoopLLM(TextGenerationProvider):
        def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
            raise RuntimeError("本脚本禁止调用 LLM")

    class _FakeRepo:
        def get(self, _pid):
            return None

    svc = ChapterGenerationWorkflowService(
        project_repo=_FakeRepo(),  # type: ignore[arg-type]
        chapter_repo=_FakeRepo(),  # type: ignore[arg-type]
        agent_run_repo=_FakeRepo(),  # type: ignore[arg-type]
        tool_call_repo=_FakeRepo(),  # type: ignore[arg-type]
        skill_run_repo=_FakeRepo(),  # type: ignore[arg-type]
        story_context_provider=type(
            "_SC",
            (),
            {
                "load": staticmethod(
                    lambda **kw: SimpleNamespace(
                        chapters=[{"id": "c1", "chapter_no": 1, "title": "上一章", "content": "…"}],
                        characters=[{"name": "主角", "id": "ch1"}],
                        world_entries=[],
                        timeline_events=[],
                        foreshadowings=[],
                    )
                )
            },
        )(),
        project_memory_service=type(
            "_PM",
            (),
            {
                "build_context": staticmethod(
                    lambda **kw: SimpleNamespace(
                        items=[
                            SimpleNamespace(source="vector", text="记忆：上一战损失", priority=0.9),
                        ]
                    )
                )
            },
        )(),
        ingestion_service=type("_Ing", (), {"ingest_text": staticmethod(lambda **kw: [])})(),  # type: ignore[arg-type]
        text_provider=_NoopLLM(),
    )
    if use_registry:
        schema_registry = SchemaRegistry(_ROOT / "packages/schemas")
        skill_registry = SkillRegistry(
            root=_ROOT / "packages/skills",
            schema_registry=schema_registry,
            strict=True,
            degrade_mode=False,
        )
        svc.agent_registry = AgentRegistry(
            root=_ROOT / "apps/agents",
            schema_registry=schema_registry,
            skill_registry=skill_registry,
            strict=True,
            degrade_mode=False,
        )
        svc.schema_registry = schema_registry
    return svc


def main() -> int:
    parser = argparse.ArgumentParser(description="打印章节 writer 上下文（不请求 LLM）")
    parser.add_argument(
        "--orchestrated",
        action="store_true",
        help="注入编排 raw_state，走 writer_draft Assembler 分支",
    )
    parser.add_argument(
        "--no-registry",
        action="store_true",
        help="不加载 apps/agents（legacy system prompt + 简单输出 schema）",
    )
    parser.add_argument(
        "--max-system-chars",
        type=int,
        default=120_000,
        help="system_prompt 超过此长度则截断显示",
    )
    args = parser.parse_args()
    use_registry = not args.no_registry
    svc = _build_service(use_registry=use_registry)

    project = SimpleNamespace(
        id="debug-project",
        title="调试项目",
        genre="科幻",
        premise="星际殖民与身份认同。",
        metadata_json={"debug": True},
    )
    memory_context = SimpleNamespace(
        items=[
            SimpleNamespace(source="mem", text="关键记忆条目一", priority=1),
        ]
    )
    story_context = SimpleNamespace(
        chapters=[{"chapter_no": 1, "title": "章1", "content": "前文摘要…"}],
        characters=[
            {
                "name": "林",
                "id": "1",
                "effective_inventory_json": {},
                "effective_wealth_json": {},
            }
        ],
        world_entries=[{"term": "跃迁", "summary": "FTL"}],
        timeline_events=[],
        foreshadowings=[],
    )
    tw = 1200
    w_low, w_high = chapter_word_count_allowed_range(tw)
    orch = _sample_orchestrator_raw_state() if args.orchestrated else None

    runtime = svc._resolve_writer_runtime(
        workflow_type=svc.WORKFLOW_NAME,
        step_key="writer_draft",
        strategy_mode="draft",
    )
    system_prompt = str(runtime.get("system_prompt") or "")
    payload = svc._build_chapter_writer_prompt_payload(
        project=project,
        writing_goal="调试：验证上下文结构，不调用模型。",
        target_words=tw,
        style_hint="冷峻、少形容词",
        memory_context=memory_context,
        story_context=story_context,
        working_notes=["工作笔记：先写对峙，再写转折。"],
        retrieval_context="【检索循环补充】仅调试字符串。" if args.orchestrated else "独立链路检索补充。",
        chapter_no=2,
        word_count_min=w_low,
        word_count_max=w_high,
        using_writer_schema=bool(runtime.get("using_writer_schema")),
        orchestrator_raw_state=orch,
    )

    branch = "writer_draft (编排)" if svc._should_use_writer_draft_assembler(orch) else "chapter_draft (独立)"
    print("=== Chapter writer 上下文调试（不请求 LLM）===\n")
    print(f"Assembler 分支: {branch}")
    print(f"step_key (user JSON): {payload.get('step_key')}")
    print(f"using_writer_schema (runtime): {runtime.get('using_writer_schema')}")
    print(f"schema_ref (runtime): {runtime.get('schema_ref')}")
    print(f"response_schema required (顶层): {list((runtime.get('response_schema') or {}).get('required') or [])}")
    print()

    max_sys = int(args.max_system_chars)
    if len(system_prompt) > max_sys:
        print(f"--- system_prompt（截断，共 {len(system_prompt)} 字符，仅显示前 {max_sys}）---")
        print(system_prompt[:max_sys])
        print("\n… [截断] …\n")
    else:
        print("--- system_prompt（全文）---")
        print(system_prompt)
    print()

    user_json = json.dumps(payload, ensure_ascii=False, indent=2)
    print("--- user 负载 JSON（将序列化后作为 user_prompt）---")
    print(user_json)
    print()
    print(f"user JSON 字符数: {len(user_json)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
