"""章节链路 retrieval_bundle 与 summary 根级双写一致性。"""

from __future__ import annotations

from packages.workflows.chapter_generation.service import ChapterGenerationWorkflowService


def test_build_chapter_retrieval_bundle_mirrors_key_facts_to_root() -> None:
    bundle = ChapterGenerationWorkflowService._build_chapter_retrieval_bundle(
        memory_items=[],
        orchestrator_retrieval_text="fact-one",
    )
    assert bundle["summary"]["key_facts"] == ["fact-one"]
    assert bundle["key_facts"] == bundle["summary"]["key_facts"]


def test_merge_retrieval_bundles_mirrors_decision_lists() -> None:
    a = {
        "summary": {
            "key_facts": ["a"],
            "current_states": ["s1"],
            "confirmed_facts": [],
            "supporting_evidence": [],
            "conflicts": [],
            "information_gaps": [],
        },
        "items": [],
        "meta": {},
    }
    b = {
        "summary": {
            "key_facts": ["b"],
            "current_states": ["s2"],
            "confirmed_facts": [],
            "supporting_evidence": [],
            "conflicts": [],
            "information_gaps": [],
        },
        "items": [],
        "meta": {},
    }
    merged = ChapterGenerationWorkflowService._merge_retrieval_bundles(a, b)
    assert merged["summary"]["key_facts"] == ["a", "b"]
    assert merged["summary"]["current_states"] == ["s1", "s2"]
    assert merged["key_facts"] == merged["summary"]["key_facts"]
    assert merged["current_states"] == merged["summary"]["current_states"]
