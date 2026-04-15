from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any
from uuid import uuid4

from packages.core.utils import estimate_token_count
from packages.workflows.orchestration.runtime_config import OrchestratorRuntimeConfig
from packages.workflows.orchestration.types import (
    EvidenceCoverageReport,
    EvidenceItem,
    RetrievalRoundDecision,
    RetrievalRoundResult,
)


_TOKEN_RE = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}")
_CONFLICT_RE = re.compile(r"(冲突|矛盾|不一致|违背|风险|warning|failed|issue)", re.IGNORECASE)


@dataclass(frozen=True)
class RetrievalLoopRequest:
    workflow_run_id: object
    workflow_step_id: object
    project_id: object
    trace_id: str | None
    step_key: str
    workflow_type: str
    writing_goal: str
    chapter_no: int | None = None
    user_id: object | None = None
    source_types: list[str] | None = None
    must_have_slots: list[str] | None = None


@dataclass(frozen=True)
class RetrievalLoopSummary:
    retrieval_trace_id: str
    rounds: list[RetrievalRoundResult] = field(default_factory=list)
    evidence_items: list[EvidenceItem] = field(default_factory=list)
    coverage: EvidenceCoverageReport = field(
        default_factory=lambda: EvidenceCoverageReport(
            coverage_score=0.0,
            resolved_slots=[],
            open_slots=[],
            enough_context=False,
            stop_reason="no_rounds",
        )
    )
    stop_reason: str = "no_rounds"
    context_text: str = ""
    context_budget_usage: dict[str, Any] = field(default_factory=dict)
    context_bundle: dict[str, Any] = field(default_factory=dict)


class RetrievalLoopService:
    """写作编排统一检索循环：计划检索 -> 证据评估 -> 停止决策。"""

    _DEFAULT_SOURCE_TYPES = [
        "project",
        "outline",
        "chapter",
        "character",
        "world_entry",
        "timeline_event",
        "foreshadowing",
        "memory_fact",
        "user_preference",
    ]
    _SLOT_SOURCE_MAP = {
        "project_goal": {"project", "outline", "memory_fact"},
        "outline": {"outline"},
        "chapter_neighborhood": {"chapter"},
        "character": {"character"},
        "world_rule": {"world_entry"},
        "timeline": {"timeline_event", "chapter"},
        "foreshadowing": {"foreshadowing"},
        "style_preference": {"user_preference"},
        "conflict_evidence": {"chapter", "memory_fact", "timeline_event", "foreshadowing"},
    }

    def __init__(
        self,
        *,
        runtime_config: OrchestratorRuntimeConfig,
        project_memory_service,
        story_context_provider,
        project_repo,
        outline_repo,
        user_repo=None,
        retrieval_trace_repo=None,
    ) -> None:
        self.runtime_config = runtime_config
        self.project_memory_service = project_memory_service
        self.story_context_provider = story_context_provider
        self.project_repo = project_repo
        self.outline_repo = outline_repo
        self.user_repo = user_repo
        self.retrieval_trace_repo = retrieval_trace_repo

    def run(self, request: RetrievalLoopRequest) -> RetrievalLoopSummary:
        retrieval_trace_id = self._build_trace_id(request)
        max_rounds = max(1, int(self.runtime_config.retrieval_max_rounds))
        top_k = max(1, int(self.runtime_config.retrieval_round_top_k))
        max_unique_evidence = max(1, int(self.runtime_config.retrieval_max_unique_evidence))
        min_coverage = float(self.runtime_config.retrieval_stop_min_coverage)
        min_gain = float(self.runtime_config.retrieval_stop_min_gain)
        stale_round_limit = max(1, int(self.runtime_config.retrieval_stop_stale_rounds))

        source_types = self._normalize_source_types(request.source_types)
        slots = self._infer_slots(
            workflow_type=request.workflow_type,
            writing_goal=request.writing_goal,
            custom_slots=request.must_have_slots,
        )
        structured_items = self._build_structured_evidence(
            request=request,
            allowed_source_types=set(source_types),
        )

        rounds: list[RetrievalRoundResult] = []
        accepted_items: list[EvidenceItem] = []
        unique_keys: set[str] = set()
        stale_rounds = 0
        base_query = str(request.writing_goal or "").strip()
        last_coverage = EvidenceCoverageReport(
            coverage_score=0.0,
            resolved_slots=[],
            open_slots=list(slots),
            enough_context=False,
            stop_reason=None,
        )
        stop_reason = "max_rounds"

        for round_index in range(1, max_rounds + 1):
            open_slots = list(last_coverage.open_slots or slots)
            selected_sources = self._select_round_sources(
                open_slots=open_slots,
                source_types=source_types,
            )
            query = self._build_round_query(
                base_query=base_query,
                workflow_type=request.workflow_type,
                open_slots=open_slots,
                round_index=round_index,
            )
            decision = RetrievalRoundDecision(
                query=query,
                intent=self._intent_for_workflow(request.workflow_type),
                source_types=list(selected_sources),
                time_scope={},
                chapter_window={
                    "before": int(self.runtime_config.context_chapter_window_before),
                    "after": int(self.runtime_config.context_chapter_window_after),
                },
                must_have_slots=list(slots),
                enough_context=False,
            )

            started = perf_counter()
            round_items = self._retrieve_round_items(
                request=request,
                decision=decision,
                structured_items=structured_items,
                top_k=top_k,
            )
            elapsed_ms = int((perf_counter() - started) * 1000)

            new_items: list[EvidenceItem] = []
            for item in round_items:
                unique_key = self._build_unique_key(item)
                if unique_key in unique_keys:
                    continue
                if len(unique_keys) >= max_unique_evidence:
                    break
                unique_keys.add(unique_key)
                accepted_items.append(item)
                new_items.append(item)

            new_evidence_gain = float(len(new_items) / max(1, top_k))
            if new_evidence_gain < min_gain:
                stale_rounds += 1
            else:
                stale_rounds = 0

            coverage = self._evaluate_coverage(
                slots=slots,
                evidence_items=accepted_items,
                min_coverage=min_coverage,
            )

            should_stop = False
            current_stop_reason = None
            if coverage.enough_context and not coverage.open_slots:
                should_stop = True
                current_stop_reason = "enough_context"
            elif coverage.coverage_score >= min_coverage and stale_rounds >= stale_round_limit:
                should_stop = True
                current_stop_reason = "stale_after_coverage"
            elif len(unique_keys) >= max_unique_evidence:
                should_stop = True
                current_stop_reason = "max_unique_evidence"
            elif round_index >= max_rounds:
                should_stop = True
                current_stop_reason = "max_rounds"

            decision = RetrievalRoundDecision(
                query=decision.query,
                intent=decision.intent,
                source_types=list(decision.source_types),
                time_scope=dict(decision.time_scope),
                chapter_window=dict(decision.chapter_window),
                must_have_slots=list(decision.must_have_slots),
                enough_context=bool(coverage.enough_context),
            )
            coverage = EvidenceCoverageReport(
                coverage_score=float(coverage.coverage_score),
                resolved_slots=list(coverage.resolved_slots),
                open_slots=list(coverage.open_slots),
                enough_context=bool(coverage.enough_context),
                stop_reason=current_stop_reason,
            )

            result = RetrievalRoundResult(
                round_index=round_index,
                decision=decision,
                coverage=coverage,
                evidence_items=list(new_items),
                new_evidence_gain=new_evidence_gain,
                latency_ms=elapsed_ms,
            )
            rounds.append(result)
            last_coverage = coverage
            stop_reason = str(current_stop_reason or stop_reason)

            self._persist_round(
                request=request,
                retrieval_trace_id=retrieval_trace_id,
                result=result,
            )

            if should_stop:
                break

        context_text, truncated, bundle_items = self._build_context_lines(accepted_items)
        used_tokens = int(estimate_token_count(context_text))
        max_context_items = 24
        context_bundle = {
            "summary": {"key_facts": [], "current_states": []},
            "items": bundle_items,
            "meta": {
                "used_tokens": used_tokens,
                "truncated": bool(truncated),
                "token_budget": None,
                "context_chars": len(context_text),
                "rounds": len(rounds),
                "unique_evidence": len(accepted_items),
                "max_unique_evidence": max_unique_evidence,
                "max_context_items": max_context_items,
            },
        }
        return RetrievalLoopSummary(
            retrieval_trace_id=retrieval_trace_id,
            rounds=rounds,
            evidence_items=accepted_items[:max_unique_evidence],
            coverage=EvidenceCoverageReport(
                coverage_score=float(last_coverage.coverage_score),
                resolved_slots=list(last_coverage.resolved_slots),
                open_slots=list(last_coverage.open_slots),
                enough_context=bool(last_coverage.enough_context),
                stop_reason=stop_reason,
            ),
            stop_reason=stop_reason,
            context_text=context_text,
            context_budget_usage=dict(context_bundle.get("meta") or {}),
            context_bundle=context_bundle,
        )

    def _build_structured_evidence(
        self,
        *,
        request: RetrievalLoopRequest,
        allowed_source_types: set[str],
    ) -> list[EvidenceItem]:
        items: list[EvidenceItem] = []
        project = self.project_repo.get(request.project_id)
        if project is not None and "project" in allowed_source_types:
            meta = getattr(project, "metadata_json", None) or {}
            project_text = "；".join(
                part
                for part in [
                    f"项目标题：{project.title}" if getattr(project, "title", None) else "",
                    f"类型：{project.genre}" if getattr(project, "genre", None) else "",
                    f"前提：{project.premise}" if getattr(project, "premise", None) else "",
                    f"目标读者：{meta['target_audience']}" if meta.get("target_audience") else "",
                    f"叙事语气：{meta['tone']}" if meta.get("tone") else "",
                    f"标签：{', '.join(meta['tags'])}" if isinstance(meta.get("tags"), list) and meta["tags"] else "",
                ]
                if part
            ).strip()
            if project_text:
                items.append(
                    EvidenceItem(
                        source_type="project",
                        source_id=str(project.id),
                        chunk_id=f"project:{project.id}",
                        text=project_text,
                        score=1.0,
                        adopted=True,
                        metadata_json={},
                    )
                )

        outline = self.outline_repo.get_active(project_id=request.project_id) or self.outline_repo.get_latest(
            project_id=request.project_id
        )
        if outline is not None and "outline" in allowed_source_types:
            outline_text = (outline.content or "").strip() or json.dumps(outline.structure_json or {}, ensure_ascii=False)
            if outline_text:
                items.append(
                    EvidenceItem(
                        source_type="outline",
                        source_id=str(outline.id),
                        chunk_id=f"outline:{outline.id}",
                        text=outline_text[:1200],
                        score=0.95,
                        adopted=True,
                        metadata_json={"version_no": int(outline.version_no or 1)},
                    )
                )

        context = self.story_context_provider.load(
            project_id=request.project_id,
            chapter_no=request.chapter_no,
            chapter_window_before=int(self.runtime_config.context_chapter_window_before),
            chapter_window_after=int(self.runtime_config.context_chapter_window_after),
        )
        if "chapter" in allowed_source_types:
            for chapter in list(context.chapters or []):
                text = str(chapter.get("summary") or chapter.get("content_preview") or "").strip()
                if not text:
                    continue
                items.append(
                    EvidenceItem(
                        source_type="chapter",
                        source_id=str(chapter.get("id")) if chapter.get("id") is not None else None,
                        chunk_id=f"chapter:{chapter.get('id')}",
                        text=text,
                        score=0.8,
                        adopted=True,
                        metadata_json={"chapter_no": chapter.get("chapter_no")},
                    )
                )
        if "character" in allowed_source_types:
            for character in list(context.characters or []):
                name = str(character.get("name") or "").strip()
                profile = character.get("profile_json") or {}
                text = f"{name}：{json.dumps(profile, ensure_ascii=False)}" if name else ""
                if not text:
                    continue
                items.append(
                    EvidenceItem(
                        source_type="character",
                        source_id=str(character.get("id")) if character.get("id") is not None else None,
                        chunk_id=f"character:{character.get('id')}",
                        text=text[:1200],
                        score=0.85,
                        adopted=True,
                        metadata_json={},
                    )
                )
        if "world_entry" in allowed_source_types:
            for world in list(context.world_entries or []):
                title = str(world.get("title") or "").strip()
                content = str(world.get("content") or "").strip()
                text = f"{title}：{content}" if (title or content) else ""
                if not text:
                    continue
                items.append(
                    EvidenceItem(
                        source_type="world_entry",
                        source_id=str(world.get("id")) if world.get("id") is not None else None,
                        chunk_id=f"world:{world.get('id')}",
                        text=text[:1200],
                        score=0.85,
                        adopted=True,
                        metadata_json={},
                    )
                )
        if "timeline_event" in allowed_source_types:
            for event in list(context.timeline_events or []):
                title = str(event.get("event_title") or "").strip()
                desc = str(event.get("event_desc") or "").strip()
                text = f"{title}：{desc}" if (title or desc) else ""
                if not text:
                    continue
                items.append(
                    EvidenceItem(
                        source_type="timeline_event",
                        source_id=str(event.get("id")) if event.get("id") is not None else None,
                        chunk_id=f"timeline:{event.get('id')}",
                        text=text[:1200],
                        score=0.8,
                        adopted=True,
                        metadata_json={"chapter_no": event.get("chapter_no")},
                    )
                )
        if "foreshadowing" in allowed_source_types:
            for line in list(context.foreshadowings or []):
                setup = str(line.get("setup_text") or "").strip()
                payoff = str(line.get("expected_payoff") or line.get("payoff_text") or "").strip()
                text = "；".join([part for part in [setup, payoff] if part]).strip()
                if not text:
                    continue
                items.append(
                    EvidenceItem(
                        source_type="foreshadowing",
                        source_id=str(line.get("id")) if line.get("id") is not None else None,
                        chunk_id=f"foreshadow:{line.get('id')}",
                        text=text[:1200],
                        score=0.8,
                        adopted=True,
                        metadata_json={"status": line.get("status")},
                    )
                )

        if "user_preference" in allowed_source_types:
            user = None
            if request.user_id and self.user_repo is not None:
                user = self.user_repo.get(request.user_id)
            if user is None and project is not None and getattr(project, "owner_user_id", None) is not None and self.user_repo is not None:
                user = self.user_repo.get(project.owner_user_id)
            if user is not None:
                pref = dict(getattr(user, "preferences", {}) or {})
                if pref:
                    items.append(
                        EvidenceItem(
                            source_type="user_preference",
                            source_id=str(user.id),
                            chunk_id=f"user_pref:{user.id}",
                            text=json.dumps(pref, ensure_ascii=False),
                            score=0.9,
                            adopted=True,
                            metadata_json={"username": getattr(user, "username", None)},
                        )
                    )
        return items

    def _retrieve_round_items(
        self,
        *,
        request: RetrievalLoopRequest,
        decision: RetrievalRoundDecision,
        structured_items: list[EvidenceItem],
        top_k: int,
    ) -> list[EvidenceItem]:
        selected = set(decision.source_types or [])
        out: list[EvidenceItem] = [
            item
            for item in structured_items
            if item.source_type in selected
        ]

        rows = []
        search_service = getattr(self.project_memory_service, "long_term_search", None)
        if search_service is not None and hasattr(search_service, "search_with_scores"):
            try:
                rows = search_service.search_with_scores(
                    project_id=request.project_id,
                    query=decision.query,
                    top_k=max(top_k * 2, top_k),
                    sort_by="relevance_then_recent",
                )
            except Exception:
                rows = []

        for row in list(rows or []):
            source_type = str(row.get("source_type") or "memory_fact").strip() or "memory_fact"
            if source_type not in selected:
                continue
            text = str(row.get("summary_text") or row.get("text") or "").strip()
            if not text:
                continue
            score = row.get("rerank_score")
            if score is None:
                score = row.get("hybrid_score")
            if score is None and row.get("distance") is not None:
                score = max(0.0, 1.0 - float(row.get("distance")))
            out.append(
                EvidenceItem(
                    source_type=source_type,
                    source_id=(str(row.get("source_id")) if row.get("source_id") is not None else None),
                    chunk_id=(str(row.get("id")) if row.get("id") is not None else None),
                    score=(float(score) if score is not None else None),
                    text=text,
                    adopted=True,
                    metadata_json=dict(row.get("metadata_json") or {}),
                )
            )

        return out

    def _evaluate_coverage(
        self,
        *,
        slots: list[str],
        evidence_items: list[EvidenceItem],
        min_coverage: float,
    ) -> EvidenceCoverageReport:
        if not slots:
            score = min(1.0, len(evidence_items) / max(1, int(self.runtime_config.retrieval_round_top_k)))
            return EvidenceCoverageReport(
                coverage_score=float(score),
                resolved_slots=[],
                open_slots=[],
                enough_context=bool(score >= min_coverage),
                stop_reason=None,
            )

        resolved: list[str] = []
        evidence_source_set = {item.source_type for item in evidence_items}
        joined_text = "\n".join(item.text for item in evidence_items).lower()
        for slot in slots:
            expected_sources = self._SLOT_SOURCE_MAP.get(slot, set())
            slot_ok = bool(expected_sources & evidence_source_set)
            if not slot_ok and slot == "conflict_evidence":
                slot_ok = bool(_CONFLICT_RE.search(joined_text))
            if not slot_ok and slot == "style_preference":
                slot_ok = "偏好" in joined_text or "风格" in joined_text
            if slot_ok:
                resolved.append(slot)
        open_slots = [slot for slot in slots if slot not in set(resolved)]
        coverage_score = float(len(resolved) / max(1, len(slots)))
        enough_context = coverage_score >= min_coverage
        return EvidenceCoverageReport(
            coverage_score=coverage_score,
            resolved_slots=resolved,
            open_slots=open_slots,
            enough_context=enough_context,
            stop_reason=None,
        )

    def _persist_round(
        self,
        *,
        request: RetrievalLoopRequest,
        retrieval_trace_id: str,
        result: RetrievalRoundResult,
    ) -> None:
        if self.retrieval_trace_repo is None:
            return
        try:
            round_row = self.retrieval_trace_repo.create_round(
                workflow_run_id=request.workflow_run_id,
                workflow_step_id=request.workflow_step_id,
                project_id=request.project_id,
                trace_id=request.trace_id,
                retrieval_trace_id=retrieval_trace_id,
                step_key=request.step_key,
                workflow_type=request.workflow_type,
                round_index=result.round_index,
                query=result.decision.query,
                intent=result.decision.intent,
                source_types_json=list(result.decision.source_types),
                time_scope_json=dict(result.decision.time_scope),
                chapter_window_json=dict(result.decision.chapter_window),
                must_have_slots_json=list(result.decision.must_have_slots),
                enough_context=bool(result.coverage.enough_context),
                coverage_score=float(result.coverage.coverage_score),
                new_evidence_gain=float(result.new_evidence_gain),
                stop_reason=result.coverage.stop_reason,
                latency_ms=result.latency_ms,
                decision_json={
                    "resolved_slots": list(result.coverage.resolved_slots),
                    "open_slots": list(result.coverage.open_slots),
                },
            )

            self.retrieval_trace_repo.create_evidence_items(
                retrieval_round_id=round_row.id,
                workflow_run_id=request.workflow_run_id,
                workflow_step_id=request.workflow_step_id,
                project_id=request.project_id,
                trace_id=request.trace_id,
                retrieval_trace_id=retrieval_trace_id,
                step_key=request.step_key,
                round_index=result.round_index,
                items=[
                    {
                        "source_type": item.source_type,
                        "source_id": item.source_id,
                        "chunk_id": item.chunk_id,
                        "score": item.score,
                        "adopted": item.adopted,
                        "text": item.text,
                        "metadata_json": dict(item.metadata_json or {}),
                    }
                    for item in list(result.evidence_items or [])
                ],
            )
        except Exception:
            # 回放是审计增强，不应阻塞主业务链路。
            return

    @staticmethod
    def _intent_for_workflow(workflow_type: str) -> str:
        mapping = {
            "outline_generation": "plan_storyline",
            "chapter_generation": "write_chapter",
            "consistency_review": "find_conflicts",
            "revision": "fix_conflicts",
        }
        return mapping.get(str(workflow_type).strip().lower(), "retrieve_context")

    @staticmethod
    def _build_trace_id(request: RetrievalLoopRequest) -> str:
        base = str(request.trace_id or "trace").strip() or "trace"
        return f"{base}:{request.step_key}:{uuid4().hex[:10]}"

    @classmethod
    def _normalize_source_types(cls, source_types: list[str] | None) -> list[str]:
        normalized = []
        for item in list(source_types or cls._DEFAULT_SOURCE_TYPES):
            value = str(item or "").strip().lower()
            if not value or value in normalized:
                continue
            normalized.append(value)
        return normalized or list(cls._DEFAULT_SOURCE_TYPES)

    @classmethod
    def _infer_slots(
        cls,
        *,
        workflow_type: str,
        writing_goal: str,
        custom_slots: list[str] | None,
    ) -> list[str]:
        if custom_slots:
            deduped = []
            for item in custom_slots:
                slot = str(item or "").strip().lower()
                if slot and slot not in deduped:
                    deduped.append(slot)
            if deduped:
                return deduped

        wf = str(workflow_type or "").strip().lower()
        if wf == "outline_generation":
            slots = ["project_goal", "character", "world_rule", "timeline", "style_preference"]
        elif wf == "consistency_review":
            slots = ["character", "world_rule", "timeline", "foreshadowing", "conflict_evidence"]
        elif wf == "revision":
            slots = ["character", "world_rule", "timeline", "foreshadowing", "conflict_evidence", "chapter_neighborhood"]
        else:
            slots = [
                "project_goal",
                "outline",
                "character",
                "world_rule",
                "timeline",
                "foreshadowing",
                "chapter_neighborhood",
                "style_preference",
            ]

        text = str(writing_goal or "")
        if "偏好" in text and "style_preference" not in slots:
            slots.append("style_preference")
        if "伏笔" in text and "foreshadowing" not in slots:
            slots.append("foreshadowing")
        return slots

    @staticmethod
    def _build_round_query(
        *,
        base_query: str,
        workflow_type: str,
        open_slots: list[str],
        round_index: int,
    ) -> str:
        query = str(base_query or "").strip()
        if round_index <= 1:
            return query
        open_hint = "、".join(open_slots[:4]) if open_slots else "关键上下文"
        if str(workflow_type).strip().lower() == "revision":
            return f"{query}；补充冲突证据：{open_hint}"
        return f"{query}；补充上下文：{open_hint}"

    @classmethod
    def _select_round_sources(
        cls,
        *,
        open_slots: list[str],
        source_types: list[str],
    ) -> list[str]:
        if not open_slots:
            return list(source_types[:4])

        selected: list[str] = []
        allowed = set(source_types)
        for slot in open_slots:
            for source_type in sorted(cls._SLOT_SOURCE_MAP.get(slot, set())):
                if source_type in allowed and source_type not in selected:
                    selected.append(source_type)
                    if len(selected) >= 4:
                        return selected
        for source_type in source_types:
            if source_type not in selected:
                selected.append(source_type)
            if len(selected) >= 4:
                break
        return selected

    @staticmethod
    def _build_unique_key(item: EvidenceItem) -> str:
        source_type = str(item.source_type or "unknown")
        source_id = str(item.source_id or "none")
        chunk_id = str(item.chunk_id or "none")
        if chunk_id == "none" and source_id == "none":
            text_key = str(item.text or "").strip()[:80]
            chunk_id = f"text:{abs(hash(text_key))}"
        return f"{source_type}:{source_id}:{chunk_id}"

    @staticmethod
    def _build_context_lines(
        evidence_items: list[EvidenceItem],
        max_items: int = 24,
    ) -> tuple[str, bool, list[dict[str, Any]]]:
        """拼装注入模型的上下文文本、是否截断、与专家 bundle.items 对齐的条目。"""
        if not evidence_items:
            return "", False, []
        priority = {
            "project": 10,
            "outline": 9,
            "user_preference": 8,
            "character": 7,
            "world_entry": 7,
            "timeline_event": 6,
            "foreshadowing": 6,
            "chapter": 5,
            "memory_fact": 4,
        }

        sorted_items = sorted(
            list(evidence_items),
            key=lambda item: (
                -priority.get(str(item.source_type), 1),
                -(float(item.score) if item.score is not None else 0.0),
            ),
        )
        cap = max(1, int(max_items))
        truncated = len(sorted_items) > cap
        lines: list[str] = []
        bundle_items: list[dict[str, Any]] = []
        for item in sorted_items[:cap]:
            text = str(item.text or "").strip()
            if not text:
                continue
            compact = " ".join(_TOKEN_RE.findall(text))
            final_text = compact if compact else text
            if len(final_text) > 240:
                truncated = True
            display = final_text[:240]
            line = f"[{item.source_type}] {display}"
            lines.append(line)
            bundle_items.append(
                {
                    "source": str(item.source_type),
                    "score": item.score,
                    "text": line,
                }
            )
        return "\n".join(lines), truncated, bundle_items
