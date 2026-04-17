from __future__ import annotations

import unittest

from packages.workflows.orchestration.prompt_payload_assembler import (
    PromptPayloadAssembler,
    build_retrieval_bundle_from_raw_state,
    build_writer_alignment_supplement_text,
)
from packages.workflows.orchestration.step_input_specs import STEP_INPUT_SPECS
from packages.workflows.orchestration.prompt_payload_types import (
    RetrievalViewSpec,
    StateDependencySpec,
    StepInputSpec,
)


class TestPromptPayloadAssembler(unittest.TestCase):
    def test_step_input_specs_context_tier(self) -> None:
        self.assertEqual(STEP_INPUT_SPECS["planner_agent"].context_tier, "planning")
        self.assertEqual(STEP_INPUT_SPECS["retrieval_agent"].context_tier, "planning")
        self.assertEqual(STEP_INPUT_SPECS["consistency_agent:chapter_audit"].context_tier, "strict_review")
        self.assertEqual(STEP_INPUT_SPECS["writer_agent:writer_revision"].context_tier, "generative")
        rv = STEP_INPUT_SPECS["writer_agent:writer_revision"].retrieval
        self.assertEqual(rv.mode, "compact_items")
        self.assertLessEqual(rv.max_items, 8)
        self.assertEqual(
            set(rv.allowed_sources or []),
            {"memory_fact", "chapter", "character_inventory", "story_state_snapshot"},
        )

    def test_build_projects_only_dependencies_not_full_state(self) -> None:
        specs = {
            "test_agent": StepInputSpec(
                role_id="test_agent",
                include_project=True,
                include_outline=False,
                dependencies=[
                    StateDependencySpec(
                        step_key="step_a",
                        required=True,
                        fields=["keep_me"],
                        compact=False,
                    ),
                ],
                retrieval=RetrievalViewSpec(mode="none"),
            )
        }
        asm = PromptPayloadAssembler(specs=specs)
        raw_state = {
            "step_a": {
                "agent_output": {"keep_me": 1, "drop_me": "x" * 5000},
                "noise": {"nested": True},
            },
            "step_b": {"agent_output": {"only_in_full": True}},
        }
        payload = asm.build(
            role_id="test_agent",
            step_key="step_x",
            workflow_type="t",
            project_context={"id": "p1", "title": "T"},
            raw_state=raw_state,
            retrieval_bundle={"summary": {"key_facts": [], "current_states": []}, "items": []},
            outline_state={},
        )
        self.assertEqual(payload["state"]["step_a"], {"keep_me": 1})
        self.assertNotIn("step_b", payload["state"])

    def test_compact_long_strings(self) -> None:
        specs = {
            "a": StepInputSpec(
                role_id="a",
                include_project=False,
                include_outline=False,
                dependencies=[
                    StateDependencySpec(
                        step_key="w",
                        required=True,
                        fields=["world_logic_summary"],
                        compact=True,
                    )
                ],
                retrieval=RetrievalViewSpec(mode="none"),
            )
        }
        asm = PromptPayloadAssembler(specs=specs)
        long_text = "字" * 900
        payload = asm.build(
            role_id="a",
            step_key="k",
            workflow_type="t",
            project_context={},
            raw_state={"w": {"view": {"world_logic_summary": long_text}}},
            retrieval_bundle={},
            outline_state={},
        )
        v = payload["state"]["w"]["world_logic_summary_summary"]
        self.assertLess(len(v), len(long_text))
        self.assertTrue(v.endswith("..."))

    def test_compact_summarizes_chapters_list_content(self) -> None:
        """story_assets 类结构：列表内章节正文过长时改为 content_summary。"""
        specs = {
            "w:cd": StepInputSpec(
                role_id="w",
                include_project=False,
                include_outline=False,
                dependencies=[
                    StateDependencySpec(
                        step_key="story_assets",
                        required=True,
                        fields=["chapters"],
                        compact=True,
                    )
                ],
                retrieval=RetrievalViewSpec(mode="none"),
            )
        }
        asm = PromptPayloadAssembler(specs=specs)
        long_body = "章" * 800
        payload = asm.build(
            role_id="w",
            step_key="cd",
            workflow_type="t",
            project_context={},
            raw_state={
                "story_assets": {
                    "view": {
                        "chapters": [
                            {"chapter_no": 1, "title": "T", "content": long_body},
                        ]
                    }
                }
            },
            retrieval_bundle={},
            outline_state={},
        )
        ch0 = payload["state"]["story_assets"]["chapters"][0]
        self.assertNotIn("content", ch0)
        self.assertIn("content_summary", ch0)
        self.assertTrue(str(ch0["content_summary"]).endswith("..."))

    def test_missing_required_dependency_raises(self) -> None:
        asm = PromptPayloadAssembler(
            specs={
                "a": StepInputSpec(
                    role_id="a",
                    dependencies=[
                        StateDependencySpec(step_key="need_me", required=True, fields=["x"])
                    ],
                    retrieval=RetrievalViewSpec(mode="none"),
                )
            }
        )
        with self.assertRaises(ValueError):
            asm.build(
                role_id="a",
                step_key="s",
                workflow_type="t",
                project_context={},
                raw_state={},
                retrieval_bundle={},
                outline_state={},
            )

    def test_plot_agent_spec_plot_beats_and_plot_brief(self) -> None:
        spec = STEP_INPUT_SPECS["plot_agent"]
        self.assertEqual(spec.outline_profile, "plot_beats")
        self.assertEqual(spec.project_profile, "plot_brief")
        self.assertEqual(spec.dependencies[0].fields, ["title", "structure_json"])
        dep_keys = [d.step_key for d in spec.dependencies]
        self.assertNotIn("retrieval_context", dep_keys)
        self.assertEqual(spec.retrieval.gap_treatment, "soft_sidebar")
        self.assertEqual(spec.retrieval.max_information_gaps, 4)

    def test_outline_plot_beats_no_long_content(self) -> None:
        """plot_beats：outline 块不出现大纲长正文，仅 structure + 短 synopsis。"""
        asm = PromptPayloadAssembler()
        long_content = "节" * 4000
        payload = asm.build(
            role_id="plot_agent",
            step_key="plot_alignment",
            workflow_type="plot_alignment",
            project_context={
                "id": "p1",
                "title": "T",
                "genre": "G",
                "premise": "x" * 2500,
                "metadata_json": {"noise": "y" * 500, "current_arc_brief": "弧光简述"},
            },
            raw_state={
                "outline_generation": {
                    "view": {
                        "title": "大纲",
                        "structure_json": {"acts": [1]},
                    }
                }
            },
            retrieval_bundle={
                "summary": {
                    "key_facts": [],
                    "current_states": [],
                    "confirmed_facts": [],
                    "supporting_evidence": [],
                    "conflicts": [],
                    "information_gaps": [],
                },
                "items": [],
            },
            outline_state={
                "title": "大纲",
                "content": long_content,
                "structure_json": {"acts": [1]},
            },
        )
        ol = payload["outline"]
        self.assertNotIn("content", ol)
        self.assertIn("content_synopsis", ol)
        self.assertLessEqual(len(str(ol.get("content_synopsis") or "")), 520)
        st = payload.get("state") or {}
        og = st.get("outline_generation") or {}
        self.assertNotIn("content", og)
        self.assertIn("structure_json", og)

    def test_retrieval_view_soft_sidebar_moves_gaps(self) -> None:
        specs = {
            "p": StepInputSpec(
                role_id="p",
                include_project=False,
                include_outline=False,
                dependencies=[],
                retrieval=RetrievalViewSpec(
                    mode="summary_only",
                    gap_treatment="soft_sidebar",
                    max_information_gaps=2,
                ),
            )
        }
        asm = PromptPayloadAssembler(specs=specs)
        payload = asm.build(
            role_id="p",
            step_key="x",
            workflow_type="t",
            project_context={},
            raw_state={},
            retrieval_bundle={
                "summary": {
                    "key_facts": [],
                    "current_states": [],
                    "confirmed_facts": [],
                    "supporting_evidence": [],
                    "conflicts": [],
                    "information_gaps": ["gap-a", "gap-b", "gap-c"],
                },
                "items": [],
            },
            outline_state={},
        )
        r = payload["retrieval"]
        self.assertNotIn("information_gaps", r)
        sg = r.get("soft_gaps") or {}
        gaps = sg.get("information_gaps") or []
        self.assertEqual(len(gaps), 2)
        self.assertTrue(all(str(x).startswith("待核实") for x in gaps))

    def test_project_plot_brief_truncates_and_filters_meta(self) -> None:
        specs = {
            "p": StepInputSpec(
                role_id="p",
                include_project=True,
                include_outline=False,
                project_profile="plot_brief",
                dependencies=[],
                retrieval=RetrievalViewSpec(mode="none"),
            )
        }
        asm = PromptPayloadAssembler(specs=specs)
        long_premise = "字" * 3000
        out = asm.build(
            role_id="p",
            step_key="x",
            workflow_type="t",
            project_context={
                "id": "p1",
                "title": "T",
                "genre": "G",
                "premise": long_premise,
                "metadata_json": {
                    "tags": ["x"],
                    "current_arc_brief": "弧",
                    "series_brief": "系列",
                },
            },
            raw_state={},
            retrieval_bundle={},
            outline_state={},
        )
        p = out["project"]
        self.assertLessEqual(len(str(p.get("premise") or "")), 1450)
        meta = p.get("metadata_json") or {}
        self.assertNotIn("tags", meta)
        self.assertEqual(meta.get("current_arc_brief"), "弧")

    def test_project_retrieval_brief_truncates_premise(self) -> None:
        specs = {
            "r": StepInputSpec(
                role_id="r",
                include_project=True,
                include_outline=False,
                project_profile="retrieval_brief",
                dependencies=[],
                retrieval=RetrievalViewSpec(mode="none"),
            )
        }
        asm = PromptPayloadAssembler(specs=specs)
        long_premise = "字" * 3000
        out = asm.build(
            role_id="r",
            step_key="x",
            workflow_type="t",
            project_context={
                "id": "p1",
                "title": "T",
                "genre": "G",
                "premise": long_premise,
                "metadata_json": {"tags": ["x"] * 20, "tone": "dark"},
            },
            raw_state={},
            retrieval_bundle={},
            outline_state={},
        )
        p = out["project"]
        self.assertLessEqual(len(str(p.get("premise") or "")), 1300)
        self.assertNotIn("tags", p.get("metadata_json") or {})
        self.assertEqual((p.get("metadata_json") or {}).get("tone"), "dark")

    def test_retrieval_bundle_summary_and_items(self) -> None:
        raw_state = {
            "retrieval_context": {
                "agent_output": {
                    "writing_context_summary": {
                        "key_facts": ["a"],
                        "current_states": ["b"],
                    },
                    "key_evidence": [{"category": "memory_fact", "snippet": "hello world"}],
                }
            }
        }
        bundle = build_retrieval_bundle_from_raw_state(raw_state)
        self.assertEqual(bundle["summary"]["key_facts"], ["a"])
        self.assertEqual(bundle["summary"]["confirmed_facts"], ["a"])
        self.assertEqual(bundle["summary"]["supporting_evidence"], ["hello world"])
        self.assertEqual(bundle["key_facts"], bundle["summary"]["key_facts"])
        self.assertEqual(bundle["confirmed_facts"], bundle["summary"]["confirmed_facts"])
        self.assertEqual(bundle["supporting_evidence"], bundle["summary"]["supporting_evidence"])
        self.assertTrue(any("hello" in str(i.get("text")) for i in bundle["items"]))

    def test_retrieval_bundle_prefers_view_over_agent_output(self) -> None:
        raw_state = {
            "retrieval_context": {
                "view": {
                    "writing_context_summary": {"key_facts": ["from_view"], "current_states": []},
                },
                "agent_output": {
                    "writing_context_summary": {"key_facts": ["legacy"], "current_states": []},
                },
            }
        }
        bundle = build_retrieval_bundle_from_raw_state(raw_state)
        self.assertEqual(bundle["summary"]["key_facts"], ["from_view"])

    def test_retrieval_view_compact_items_respects_max(self) -> None:
        specs = {
            "r": StepInputSpec(
                role_id="r",
                include_project=False,
                include_outline=False,
                dependencies=[],
                retrieval=RetrievalViewSpec(mode="compact_items", max_items=2, max_chars_per_item=10),
            )
        }
        asm = PromptPayloadAssembler(specs=specs)
        bundle = {
            "summary": {"key_facts": [], "current_states": []},
            "items": [
                {"source": "s1", "text": "0123456789abcdef"},
                {"source": "s2", "text": "bbbbbbbb"},
                {"source": "s3", "text": "c"},
            ],
        }
        payload = asm.build(
            role_id="r",
            step_key="x",
            workflow_type="t",
            project_context={},
            raw_state={},
            retrieval_bundle=bundle,
            outline_state={},
        )
        self.assertEqual(len(payload["retrieval"]["items"]), 2)
        self.assertLessEqual(len(payload["retrieval"]["items"][0]["text"]), 10)

    def test_retrieval_view_includes_layered_summary_fields(self) -> None:
        """Writer 消费契约：summary_only 也须含五段分层字段（可为空列表）。"""
        specs = {
            "w": StepInputSpec(
                role_id="w",
                include_project=False,
                include_outline=False,
                dependencies=[],
                retrieval=RetrievalViewSpec(mode="summary_only"),
            )
        }
        asm = PromptPayloadAssembler(specs=specs)
        bundle = {
            "summary": {
                "key_facts": ["kf"],
                "current_states": ["cs"],
                "confirmed_facts": ["cf"],
                "supporting_evidence": ["se"],
                "conflicts": [{"a": 1}],
                "information_gaps": ["gap"],
            },
            "items": [],
        }
        payload = asm.build(
            role_id="w",
            step_key="x",
            workflow_type="t",
            project_context={},
            raw_state={},
            retrieval_bundle=bundle,
            outline_state={},
        )
        r = payload["retrieval"]
        self.assertEqual(r["key_facts"], ["kf"])
        self.assertEqual(r["current_states"], ["cs"])
        self.assertEqual(r["confirmed_facts"], ["cf"])
        self.assertEqual(r["supporting_evidence"], ["se"])
        self.assertEqual(r["conflicts"], [{"a": 1}])
        self.assertEqual(r["information_gaps"], ["gap"])
        self.assertNotIn("items", r)

    def test_retrieval_view_reads_decision_fields_from_root_only(self) -> None:
        """五段仅在根、summary 无对应字段时，Assembler 仍产出分层 retrieval view。"""
        specs = {
            "w": StepInputSpec(
                role_id="w",
                include_project=False,
                include_outline=False,
                dependencies=[],
                retrieval=RetrievalViewSpec(mode="summary_only"),
            )
        }
        asm = PromptPayloadAssembler(specs=specs)
        bundle = {
            "summary": {},
            "key_facts": ["kf_root"],
            "confirmed_facts": ["cf"],
            "current_states": ["cs"],
            "supporting_evidence": ["se"],
            "conflicts": [{"a": 2}],
            "information_gaps": ["gap"],
            "items": [],
        }
        payload = asm.build(
            role_id="w",
            step_key="x",
            workflow_type="t",
            project_context={},
            raw_state={},
            retrieval_bundle=bundle,
            outline_state={},
        )
        r = payload["retrieval"]
        self.assertEqual(r["key_facts"], ["kf_root"])
        self.assertEqual(r["confirmed_facts"], ["cf"])
        self.assertEqual(r["current_states"], ["cs"])
        self.assertEqual(r["supporting_evidence"], ["se"])
        self.assertEqual(r["conflicts"], [{"a": 2}])
        self.assertEqual(r["information_gaps"], ["gap"])

    def test_retrieval_decision_aliases_retrieval_same_object(self) -> None:
        """顶层 retrieval_decision 与 retrieval 指向同一决策包，避免双轨漂移。"""
        specs = {
            "w": StepInputSpec(
                role_id="w",
                include_project=False,
                include_outline=False,
                dependencies=[],
                retrieval=RetrievalViewSpec(mode="summary_only"),
            )
        }
        asm2 = PromptPayloadAssembler(specs=specs)
        out = asm2.build(
            role_id="w",
            step_key="x",
            workflow_type="t",
            project_context={},
            raw_state={},
            retrieval_bundle={
                "summary": {
                    "key_facts": ["a"],
                    "current_states": ["b"],
                    "confirmed_facts": ["c"],
                    "supporting_evidence": [],
                    "conflicts": [],
                    "information_gaps": [],
                },
                "items": [],
            },
            outline_state={},
        )
        self.assertIs(out["retrieval"], out["retrieval_decision"])
        self.assertEqual(out["retrieval"]["confirmed_facts"], ["c"])

    def test_payload_chunk_chars_includes_goal_and_contract(self) -> None:
        """_payload_chunk_char_sizes 覆盖 goal / writing_contract 等 writer 顶层块。"""
        asm = PromptPayloadAssembler()
        payload = {
            "project": {"id": "p"},
            "state": {"a": {"x": 1}},
            "goal": "写作目标",
            "target_words": 1200,
            "style_hint": "冷峻",
            "writing_contract": {"word_count_metric": "非空白字符数"},
            "output_format": {"schema_ref": "inline://x"},
        }
        chunks = asm._payload_chunk_char_sizes(payload)
        self.assertIn("goal", chunks)
        self.assertIn("target_words", chunks)
        self.assertIn("style_hint", chunks)
        self.assertIn("writing_contract", chunks)
        self.assertIn("output_format", chunks)
        self.assertIn("state.a", chunks)

    def test_build_writer_alignment_supplement_text(self) -> None:
        raw_state = {
            "plot_alignment": {
                "view": {
                    "narcotic_arc": [
                        {
                            "phase": "p1",
                            "plot_beat": "进入冲突",
                            "conflict_level": 5,
                            "pacing_note": "紧",
                            "outcome": "升级",
                        }
                    ]
                }
            },
            "character_alignment": {
                "view": {"constraints": {"must_do": ["守住秘密"], "must_not": []}},
            },
            "world_alignment": {"view": {"hard_constraints": [], "reusable_assets": {}}},
            "style_alignment": {"view": {"micro_constraints": {}}},
            "retrieval_context": {"view": {}},
        }
        text = build_writer_alignment_supplement_text(raw_state)
        self.assertIn("Plot Beats", text)
        self.assertIn("进入冲突", text)
        self.assertIn("守住秘密", text)


if __name__ == "__main__":
    unittest.main()
