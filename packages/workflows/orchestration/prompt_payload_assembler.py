"""将 raw_state 投影为当前步骤 LLM 所需的最小 prompt payload。"""

from __future__ import annotations

import json
import logging
from typing import Any

from packages.workflows.orchestration.agent_output_envelope import step_agent_view
from packages.workflows.orchestration.prompt_payload_types import StepInputSpec
from packages.workflows.orchestration.step_input_specs import STEP_INPUT_SPECS

logger = logging.getLogger(__name__)

# 工作流步骤 output_json 中与「可依赖视图」无关、体积可能较大的信封字段
_STEP_OUTPUT_ENVELOPE_KEYS = frozenset(
    {
        "skill_runs",
        "skills_executed_count",
        "skills_effective_delta",
        "warnings",
        "mock_mode",
        "retrieval_trace_id",
        "retrieval_rounds",
        "retrieval_stop_reason",
        "evidence_coverage",
        "open_slots",
        "context_budget_usage",
        "memory_ingestion",
        "agent_run_id",
        "waiting_review",
        "writer_guidance",
        "notes",
        "schema_ref",
        "prompt_hash",
        "schema_version",
        "role_id",
        "agent_name",
        "step_key",
        "view",
        "meta",
        "raw",
    }
)


class PromptPayloadAssembler:
    """按 StepInputSpec 把全局运行态投影为单步 LLM 输入。"""

    def __init__(self, specs: dict[str, StepInputSpec] | None = None) -> None:
        self.specs = specs if specs is not None else STEP_INPUT_SPECS

    def _get_spec(self, role_id: str, step_key: str) -> StepInputSpec:
        rid = str(role_id or "").strip().lower()
        skid = str(step_key or "").strip()
        composite = f"{rid}:{skid}" if skid else rid
        spec = self.specs.get(composite) or self.specs.get(rid)
        if not spec:
            raise ValueError(f"缺少 StepInputSpec：role_id={rid!r} step_key={skid!r}")
        return spec

    def build(
        self,
        *,
        role_id: str,
        step_key: str,
        workflow_type: str,
        project_context: dict[str, Any],
        raw_state: dict[str, dict],
        retrieval_bundle: dict[str, Any],
        outline_state: dict[str, Any],
        working_notes: dict[str, Any] | list[str] | None = None,
    ) -> dict[str, Any]:
        spec = self._get_spec(role_id, step_key)
        missing_deps = self._missing_required_dependencies(spec, raw_state)
        if missing_deps:
            logger.error(
                json.dumps(
                    {
                        "event": "prompt_payload_missing_dependencies",
                        "role_id": str(role_id or "").strip().lower(),
                        "step_key": str(step_key or ""),
                        "missing_required_dependencies": missing_deps,
                    },
                    ensure_ascii=False,
                )
            )
            raise ValueError(
                f"步骤 {spec.role_id!r} 缺少必需依赖步骤 output：{missing_deps}"
            )

        payload: dict[str, Any] = {
            "step_key": step_key,
            "workflow_type": workflow_type,
            "role_id": role_id,
        }

        if spec.include_project:
            payload["project"] = self._build_project_view(project_context)

        if spec.include_outline:
            payload["outline"] = self._build_outline_view(outline_state)

        state_view = self._build_state_view(spec, raw_state)
        payload["state"] = state_view

        retrieval_view = self._build_retrieval_view(spec, retrieval_bundle)
        if retrieval_view:
            payload["retrieval"] = retrieval_view

        if spec.include_working_notes and working_notes:
            payload["working_notes"] = self._build_working_notes_view(working_notes)

        payload_size_chars = len(json.dumps(payload, ensure_ascii=False))
        chunk_chars = self._payload_chunk_char_sizes(payload)
        logger.info(
            json.dumps(
                {
                    "event": "prompt_payload_built",
                    "role_id": str(role_id or "").strip().lower(),
                    "step_key": str(step_key or ""),
                    "context_tier": spec.context_tier,
                    "raw_state_keys": sorted(raw_state.keys()),
                    "projected_state_keys": sorted(state_view.keys()),
                    "dependency_keys": [d.step_key for d in spec.dependencies],
                    "retrieval_mode": spec.retrieval.mode,
                    "payload_size_chars": payload_size_chars,
                    "payload_chunk_chars": chunk_chars,
                },
                ensure_ascii=False,
            )
        )
        if spec.context_tier == "planning":
            st = int(chunk_chars.get("state") or 0)
            rt = int(chunk_chars.get("retrieval") or 0)
            if st + rt > 12_000:
                logger.warning(
                    json.dumps(
                        {
                            "event": "prompt_payload_planning_budget_soft_cap",
                            "role_id": str(role_id or "").strip().lower(),
                            "step_key": str(step_key or ""),
                            "state_chars": st,
                            "retrieval_chars": rt,
                            "hint": "规划档建议保持轻量；检查 dependencies 是否带入过长字段",
                        },
                        ensure_ascii=False,
                    )
                )
        return payload

    @staticmethod
    def _payload_chunk_char_sizes(payload: dict[str, Any]) -> dict[str, int]:
        """各顶层块序列化字符数，便于 summary-first 体积对照。"""
        out: dict[str, int] = {}
        for key in (
            "project",
            "outline",
            "state",
            "retrieval",
            "working_notes",
            "goal",
            "target_words",
            "style_hint",
            "writing_contract",
            "output_format",
        ):
            if key not in payload:
                continue
            try:
                out[key] = len(json.dumps(payload[key], ensure_ascii=False))
            except (TypeError, ValueError):
                out[key] = -1
        st = payload.get("state")
        if isinstance(st, dict):
            for sk, sv in st.items():
                try:
                    out[f"state.{sk}"] = len(json.dumps(sv, ensure_ascii=False))
                except (TypeError, ValueError):
                    out[f"state.{sk}"] = -1
        return out

    def _missing_required_dependencies(
        self, spec: StepInputSpec, raw_state: dict[str, dict]
    ) -> list[str]:
        missing: list[str] = []
        for dep in spec.dependencies:
            if dep.required and dep.step_key not in raw_state:
                missing.append(dep.step_key)
        return missing

    def _build_state_view(
        self,
        spec: StepInputSpec,
        raw_state: dict[str, dict],
    ) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for dep in spec.dependencies:
            src_step = raw_state.get(dep.step_key)
            if not isinstance(src_step, dict):
                continue

            section = self._resolve_section_dict(src_step, dep.from_section)
            projected = self._project_fields(section, dep.fields)
            if dep.compact:
                projected = self._compact_step_output(dep.step_key, projected)

            if not projected:
                continue

            key = dep.rename_to or dep.step_key
            result[key] = projected
        return result

    def _resolve_section_dict(self, raw_step_output: dict[str, Any], from_section: str) -> dict[str, Any]:
        fs = str(from_section or "view").strip().lower()
        if fs == "meta":
            meta = raw_step_output.get("meta")
            return dict(meta) if isinstance(meta, dict) else {}

        if fs == "view":
            merged = step_agent_view(raw_step_output)
            if merged:
                return merged
            return {
                k: v
                for k, v in raw_step_output.items()
                if k not in _STEP_OUTPUT_ENVELOPE_KEYS
            }

        # 未知 section 时退回 view 规则
        return self._resolve_section_dict(raw_step_output, "view")

    def _project_fields(self, src: dict[str, Any], fields: list[str]) -> dict[str, Any]:
        if not fields:
            return {}
        return {k: src[k] for k in fields if k in src}

    def _compact_step_output(self, step_key: str, data: dict[str, Any]) -> dict[str, Any]:
        del step_key
        out = dict(data)
        ch = out.get("chapter")
        if isinstance(ch, dict) and isinstance(ch.get("content"), str):
            ch_copy = dict(ch)
            ch_copy["content_summary"] = self._summarize_long_text(str(ch_copy.get("content") or ""))
            ch_copy.pop("content", None)
            out["chapter"] = ch_copy
        # story_assets 等：chapters 为列表时每章正文单独压摘要，避免整段历史全文进入 user JSON。
        chapters = out.get("chapters")
        if isinstance(chapters, list):
            out["chapters"] = self._compact_chapter_list_items(chapters)
        long_text_fields = [
            "content",
            "full_text",
            "analysis_raw",
            "raw_notes",
            "reference_chunks",
            "draft_content",
            "world_logic_summary",
            "audit_summary",
        ]
        for field in long_text_fields:
            val = out.get(field)
            if isinstance(val, str):
                out[f"{field}_summary"] = self._summarize_long_text(val)
                out.pop(field, None)
            elif isinstance(val, list) and field == "reference_chunks":
                out["reference_chunk_summaries"] = [self._summarize_chunk(x) for x in val[:5]]
                out.pop(field, None)
        return out

    def _compact_chapter_list_items(self, chapters: list[Any]) -> list[Any]:
        compacted: list[Any] = []
        for item in chapters:
            if not isinstance(item, dict):
                compacted.append(item)
                continue
            cpy = dict(item)
            raw = cpy.get("content")
            if isinstance(raw, str) and raw.strip():
                lim = 600
                if len(raw.strip()) > lim:
                    cpy["content_summary"] = self._summarize_long_text(raw, limit=lim)
                    cpy.pop("content", None)
            compacted.append(cpy)
        return compacted

    def _summarize_long_text(self, text: str, limit: int = 600) -> str:
        text = str(text or "").strip()
        if len(text) <= limit:
            return text
        return text[:limit] + "..."

    def _summarize_chunk(self, item: dict[str, Any], limit: int = 200) -> dict[str, Any]:
        return {
            "source": item.get("source"),
            "score": item.get("score"),
            "text": str(item.get("text") or "")[:limit],
        }

    def _build_retrieval_view(
        self,
        spec: StepInputSpec,
        retrieval_bundle: dict[str, Any],
    ) -> dict[str, Any]:
        rv = spec.retrieval
        if rv.mode == "none":
            return {}

        summary = dict(retrieval_bundle.get("summary") or {})
        key_facts = list(summary.get("key_facts") or retrieval_bundle.get("key_facts") or [])
        current_states = list(
            summary.get("current_states") or retrieval_bundle.get("current_states") or []
        )

        if rv.mode == "summary_only":
            return {
                "key_facts": key_facts,
                "current_states": current_states,
            }

        raw_items = list(retrieval_bundle.get("items") or [])
        if rv.mode == "compact_items":
            items: list[dict[str, Any]] = []
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                if rv.allowed_sources and item.get("source") not in rv.allowed_sources:
                    continue
                items.append(
                    {
                        "source": item.get("source"),
                        "score": item.get("score"),
                        "text": str(item.get("text") or "")[: rv.max_chars_per_item],
                    }
                )
                if len(items) >= rv.max_items:
                    break
            return {
                "key_facts": key_facts,
                "current_states": current_states,
                "items": items,
            }

        if rv.mode == "full_items":
            items_full: list[dict[str, Any]] = []
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                if rv.allowed_sources and item.get("source") not in rv.allowed_sources:
                    continue
                items_full.append(dict(item))
                if len(items_full) >= rv.max_items:
                    break
            return {"items": items_full}

        return {}

    def _build_project_view(self, project_context: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": project_context.get("id"),
            "title": project_context.get("title"),
            "genre": project_context.get("genre"),
            "premise": project_context.get("premise"),
            "metadata_json": project_context.get("metadata_json") or {},
        }

    def _build_outline_view(self, outline_state: dict[str, Any]) -> dict[str, Any]:
        structure = outline_state.get("structure_json")
        if not isinstance(structure, dict):
            structure = {}
        raw_content = outline_state.get("content")
        content_out: Any = raw_content
        if isinstance(raw_content, str) and len(raw_content) > 2400:
            content_out = self._summarize_long_text(raw_content, limit=1200)
        return {
            "title": outline_state.get("title"),
            "content": content_out,
            "structure_json": structure,
        }

    def _build_working_notes_view(
        self,
        working_notes: dict[str, Any] | list[str],
    ) -> dict[str, Any]:
        if isinstance(working_notes, list):
            return {"lines": [str(x).strip() for x in working_notes if str(x).strip()]}
        return dict(working_notes)


def build_retrieval_bundle_from_raw_state(raw_state: dict[str, dict]) -> dict[str, Any]:
    """从 retrieval_context 步骤构造双层检索包：summary + items + meta。"""
    step = dict(raw_state.get("retrieval_context") or {})
    agent_out = step_agent_view(step)
    if not isinstance(agent_out, dict) or not agent_out:
        return {
            "summary": {
                "key_facts": [],
                "current_states": [],
                "confirmed_facts": [],
                "supporting_evidence": [],
                "conflicts": [],
                "information_gaps": [],
            },
            "items": [],
            "meta": {},
        }

    summary_obj = dict(agent_out.get("writing_context_summary") or {})
    key_facts = [str(x).strip() for x in list(summary_obj.get("key_facts") or []) if str(x).strip()]
    current_states = [
        str(x).strip() for x in list(summary_obj.get("current_states") or []) if str(x).strip()
    ]
    items: list[dict[str, Any]] = []
    for ev in list(agent_out.get("key_evidence") or []):
        if isinstance(ev, dict):
            items.append(
                {
                    "source": str(ev.get("category") or "key_evidence"),
                    "score": None,
                    "text": str(ev.get("snippet") or ""),
                }
            )
    for cf in list(agent_out.get("potential_conflicts") or []):
        if isinstance(cf, dict):
            desc = str(cf.get("description") or "").strip()
            if desc:
                items.append({"source": "potential_conflict", "score": None, "text": desc[:800]})

    gaps = [str(x).strip() for x in list(agent_out.get("information_gaps") or []) if str(x).strip()]
    conflicts_summary: list[str] = []
    for cf in list(agent_out.get("potential_conflicts") or []):
        if isinstance(cf, dict):
            desc = str(cf.get("description") or "").strip()
            if desc:
                conflicts_summary.append(desc[:1200])
    supporting_evidence: list[str] = []
    for ev in list(agent_out.get("key_evidence") or []):
        if isinstance(ev, dict):
            sn = str(ev.get("snippet") or "").strip()
            if sn:
                supporting_evidence.append(sn[:1200])

    return {
        "summary": {
            "key_facts": key_facts,
            "current_states": current_states,
            "confirmed_facts": list(key_facts),
            "supporting_evidence": supporting_evidence,
            "conflicts": conflicts_summary,
            "information_gaps": gaps,
        },
        "items": items,
        "meta": {},
    }


def build_writer_alignment_supplement_text(raw_state: dict[str, Any]) -> str:
    """
    从 raw_state 中各 alignment / retrieval 步骤生成一段说明文本。

    用于 revision 等仍消费「纯文本检索补充」的链路；章节草稿主链路已改用 Assembler JSON。
    """
    plot_output = step_agent_view(dict(raw_state.get("plot_alignment") or {}))
    character_output = step_agent_view(dict(raw_state.get("character_alignment") or {}))
    world_output = step_agent_view(dict(raw_state.get("world_alignment") or {}))
    style_output = step_agent_view(dict(raw_state.get("style_alignment") or {}))
    retrieval_output = step_agent_view(dict(raw_state.get("retrieval_context") or {}))

    lines: list[str] = []

    beats = [dict(x) for x in list(plot_output.get("narcotic_arc") or []) if isinstance(x, dict)]
    if beats:
        lines.append("## Plot Beats (Must Follow)")
        for idx, beat in enumerate(beats[:6], start=1):
            phase = str(beat.get("phase") or f"phase-{idx}").strip()
            instruction = str(beat.get("plot_beat") or "").strip()
            pacing = str(beat.get("pacing_note") or "").strip()
            conflict = beat.get("conflict_level")
            if not instruction:
                continue
            lines.append(
                f"- [{phase}] {instruction}"
                + (f"（冲突等级:{conflict}）" if conflict is not None else "")
                + (f"；节奏:{pacing}" if pacing else "")
            )

    constraints = dict(character_output.get("constraints") or {})
    must_do = [str(x).strip() for x in list(constraints.get("must_do") or []) if str(x).strip()]
    must_not = [str(x).strip() for x in list(constraints.get("must_not") or []) if str(x).strip()]
    if must_do or must_not:
        lines.append("## Character Constraints")
        for item in must_do[:8]:
            lines.append(f"- 必须执行: {item}")
        for item in must_not[:8]:
            lines.append(f"- 禁止行为: {item}")

    hard_rules = [dict(x) for x in list(world_output.get("hard_constraints") or []) if isinstance(x, dict)]
    if hard_rules:
        lines.append("## World System Constraints (ABSOLUTE)")
        for rule in hard_rules[:8]:
            rule_type = str(rule.get("rule_type") or "rule").strip().upper()
            desc = str(rule.get("rule_description") or "").strip()
            limit = str(rule.get("limitation") or "").strip()
            if not desc:
                continue
            lines.append(f"- [{rule_type}] {desc}" + (f"；限制: {limit}" if limit else ""))
        lines.append("- 禁止机械降神：不得凭空引入违反世界规则的新设定。")

    assets = dict(world_output.get("reusable_assets") or {})
    locations = [str(x).strip() for x in list(assets.get("locations") or []) if str(x).strip()]
    factions = [str(x).strip() for x in list(assets.get("factions") or []) if str(x).strip()]
    items_concepts = [str(x).strip() for x in list(assets.get("items_concepts") or []) if str(x).strip()]
    if locations or factions or items_concepts:
        lines.append("## Available Assets (Use these first)")
        if locations:
            lines.append("- Locations: " + "、".join(locations[:12]))
        if factions:
            lines.append("- Factions: " + "、".join(factions[:12]))
        if items_concepts:
            lines.append("- Items: " + "、".join(items_concepts[:12]))

    style_micro = dict(style_output.get("micro_constraints") or {})
    sentence_structure = str(style_micro.get("sentence_structure") or "").strip()
    vocab_level = str(style_micro.get("vocabulary_level") or "").strip()
    forbidden_words = [str(x).strip() for x in list(style_micro.get("forbidden_words") or []) if str(x).strip()]
    rhythm = dict(style_output.get("rhythm_strategy") or {})
    rhythm_instruction = str(rhythm.get("instruction") or "").strip()
    if sentence_structure or vocab_level or forbidden_words or rhythm_instruction:
        lines.append("## Style Constraints")
        if sentence_structure:
            lines.append(f"- Sentence: {sentence_structure}")
        if vocab_level:
            lines.append(f"- Vocabulary: {vocab_level}")
        if rhythm_instruction:
            lines.append(f"- Rhythm: {rhythm_instruction}")
        if forbidden_words:
            lines.append("- Forbidden: " + "、".join(forbidden_words[:16]))

    retrieval_summary = dict(retrieval_output.get("writing_context_summary") or {})
    key_facts = [str(x).strip() for x in list(retrieval_summary.get("key_facts") or []) if str(x).strip()]
    current_states = [str(x).strip() for x in list(retrieval_summary.get("current_states") or []) if str(x).strip()]
    conflicts = [dict(x) for x in list(retrieval_output.get("potential_conflicts") or []) if isinstance(x, dict)]
    info_gaps = [str(x).strip() for x in list(retrieval_output.get("information_gaps") or []) if str(x).strip()]
    if key_facts or current_states or conflicts or info_gaps:
        lines.append("## Retrieval Synthesis")
        for fact in key_facts[:12]:
            lines.append(f"- Fact: {fact}")
        for state_item in current_states[:12]:
            lines.append(f"- State: {state_item}")
        for conflict in conflicts[:6]:
            desc = str(conflict.get("description") or "").strip()
            sources = [str(x).strip() for x in list(conflict.get("conflicting_sources") or []) if str(x).strip()]
            if desc:
                lines.append(
                    f"- Conflict: {desc}" + (f"（sources: {'/'.join(sources[:4])}）" if sources else "")
                )
        for gap in info_gaps[:6]:
            lines.append(f"- Gap: {gap}")

    return "\n".join(lines).strip()
