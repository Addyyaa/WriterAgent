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
        logger.info(
            json.dumps(
                {
                    "event": "prompt_payload_built",
                    "role_id": str(role_id or "").strip().lower(),
                    "step_key": str(step_key or ""),
                    "raw_state_keys": sorted(raw_state.keys()),
                    "projected_state_keys": sorted(state_view.keys()),
                    "dependency_keys": [d.step_key for d in spec.dependencies],
                    "retrieval_mode": spec.retrieval.mode,
                    "payload_size_chars": payload_size_chars,
                },
                ensure_ascii=False,
            )
        )
        return payload

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
            "summary": {"key_facts": [], "current_states": []},
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

    return {
        "summary": {"key_facts": key_facts, "current_states": current_states},
        "items": items,
        "meta": {},
    }
