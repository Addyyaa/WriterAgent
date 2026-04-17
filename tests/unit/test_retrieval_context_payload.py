"""retrieval_context 步骤：预检索 bundle + planner_retrieval_intent + 收窄 project。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from packages.core.context_bundle_decision import mirror_context_bundle_lists_from_summary
from packages.workflows.orchestration.prompt_payload_assembler import PromptPayloadAssembler
from packages.workflows.orchestration.retrieval_loop import RetrievalLoopSummary
from packages.workflows.orchestration.service import WritingOrchestratorService
from packages.workflows.orchestration.step_input_specs import STEP_INPUT_SPECS


def test_retrieval_context_payload_uses_prefetch_and_intent() -> None:
    stub_bundle: dict = {
        "summary": {
            "key_facts": ["loop_kf"],
            "current_states": [],
            "confirmed_facts": [],
            "supporting_evidence": ["support line"],
            "conflicts": [],
            "information_gaps": [],
        },
        "items": [{"source": "chapter", "text": "prefetched evidence", "score": 0.9}],
        "meta": {},
    }
    mirror_context_bundle_lists_from_summary(stub_bundle)

    proj = SimpleNamespace(
        title="P",
        genre="g",
        premise="x" * 3000,
        metadata_json={"tags": ["a"] * 50, "target_audience": "YA", "tone": "冷"},
    )

    row = SimpleNamespace(
        id="run-1",
        project_id="proj-1",
        trace_id="tr-1",
        initiated_by="u1",
        input_json={
            "writing_goal": "写第2章",
            "chapter_no": 2,
            "focus_character_id": "c1",
        },
    )
    step = SimpleNamespace(
        id="st-1",
        step_key="retrieval_context",
        step_type="agent",
        input_json={"workflow_type": "writing_full"},
    )
    raw_state = {
        "planner_bootstrap": {
            "view": {
                "global_required_slots": ["character"],
                "steps": [{"required_slots": ["world_rule"], "preferred_tools": [], "must_verify_facts": []}],
            }
        }
    }

    svc = WritingOrchestratorService.__new__(WritingOrchestratorService)
    svc.project_repo = MagicMock()
    svc.project_repo.get.return_value = proj
    svc.story_state_snapshot_repo = None
    svc.agent_registry = MagicMock()
    svc.agent_registry.local_data_tools_catalog.return_value = []
    svc.prompt_payload_assembler = PromptPayloadAssembler()
    svc.retrieval_loop = MagicMock()

    svc._run_retrieval_loop = MagicMock(
        return_value=RetrievalLoopSummary(
            retrieval_trace_id="prefetch-1",
            context_bundle=stub_bundle,
        )
    )

    payload = WritingOrchestratorService._build_role_prompt_payload(
        svc,
        row=row,
        step=step,
        raw_state=raw_state,
        role_id="retrieval_agent",
    )

    assert payload["retrieval_evidence_status"] == "ok"
    st = payload.get("state") or {}
    assert "planner_retrieval_intent" in st
    assert "planner_bootstrap" not in st
    intent = st["planner_retrieval_intent"]
    assert intent.get("writing_goal") == "写第2章"
    assert "character" in (intent.get("normalized_required_slots") or [])
    assert "world_rule" in (intent.get("normalized_required_slots") or [])

    rv = payload.get("retrieval") or {}
    items = rv.get("items") or []
    assert items and "prefetched" in str(items[0].get("text", ""))
    blob = json.dumps(rv, ensure_ascii=False)
    assert "prefetched" in blob or "loop_kf" in blob

    proj_out = payload.get("project") or {}
    assert len(str(proj_out.get("premise") or "")) <= 1300
    meta = proj_out.get("metadata_json") or {}
    assert "tags" not in meta
    assert meta.get("tone") == "冷"


def test_retrieval_agent_spec_depends_on_planner_intent() -> None:
    spec = STEP_INPUT_SPECS["retrieval_agent"]
    assert spec.project_profile == "retrieval_brief"
    assert spec.dependencies[0].step_key == "planner_retrieval_intent"
