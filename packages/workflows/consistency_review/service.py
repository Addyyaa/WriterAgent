from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from packages.core.config import env_bool, env_int
from packages.llm.text_generation.base import TextGenerationProvider, TextGenerationRequest
from packages.llm.text_generation.openai_compatible import OpenAICompatibleTextProvider
from packages.llm.text_generation.runtime_config import TextGenerationRuntimeConfig
from packages.storage.postgres.repositories.chapter_repository import ChapterRepository
from packages.storage.postgres.repositories.consistency_report_repository import (
    ConsistencyReportRepository,
)
from packages.workflows.chapter_generation.context_provider import (
    SQLAlchemyStoryContextProvider,
    StoryConstraintContext,
)
from packages.workflows.consistency_review.context_builder import (
    build_review_context_slice,
    build_review_contract,
    build_review_evidence_pack,
    build_review_focus,
    collect_review_fetch_allowlist,
)
from packages.workflows.consistency_review.evidence_tool_loop import (
    run_consistency_review_tool_loop,
)
from packages.workflows.consistency_review.retrieval_dedup import (
    dedupe_retrieval_bundle_against_evidence,
)
from packages.workflows.orchestration.prompt_payload_assembler import PromptPayloadAssembler


@dataclass(frozen=True)
class ConsistencyReviewRequest:
    project_id: object
    chapter_id: object
    chapter_version_id: int | None = None
    trace_id: str | None = None
    # 与 writer 一致的检索包（summary/items）；长文本请写入 items[].text，勿另传平行字符串入口
    retrieval_bundle: dict[str, Any] | None = None
    # 供 PromptPayloadAssembler 的 project 投影；缺省时仅含 project_id
    project_snapshot: dict[str, Any] | None = None
    llm_enabled: bool = True
    llm_system_prompt: str | None = None
    llm_temperature: float | None = None
    llm_max_tokens: int | None = None
    llm_response_schema: dict[str, Any] | None = None
    llm_schema_ref: str | None = None
    llm_role_id: str = "consistency_agent"
    llm_strategy_version: str | None = None
    llm_prompt_hash: str | None = None


@dataclass(frozen=True)
class ConsistencyReviewResult:
    report_id: str
    status: str
    score: float | None
    summary: str
    issues: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    llm_used: bool
    rule_issues_count: int
    llm_issues_count: int


class ConsistencyReviewWorkflowService:
    AGENT_NAME = "consistency_agent"
    WORKFLOW_NAME = "consistency_review"
    DEFAULT_SYSTEM_PROMPT = (
        "你是作品一致性审查助手。仅依据 state.review_contract 中的 evidence_policy，"
        "使用 state.review_focus、state.review_context、state.review_evidence_pack 与 retrieval 证据项，"
        "对照 chapter_draft_audit 全文，输出函数 consistency_review_output 所要求的结构化结果；"
        "勿臆造未提供证据。禁止调用任何「本地数据工具」——证据已由服务端注入。"
    )
    # 与 PromptPayloadAssembler 输出对齐；output_schema 由 response_schema + 工具调用承载，不再重复进 prompt
    CONSISTENCY_INPUT_SCHEMA = {
        "type": "object",
        "required": ["state"],
        "properties": {
            "step_key": {"type": "string"},
            "workflow_type": {"type": "string"},
            "role_id": {"type": "string"},
            "project": {"type": "object"},
            "state": {"type": "object"},
            "retrieval": {"type": "object"},
        },
        "additionalProperties": True,
    }
    CONSISTENCY_OUTPUT_SCHEMA = {
        "type": "object",
        "required": ["overall_status", "audit_summary", "issues"],
        "properties": {
            "overall_status": {
                "type": "string",
                "enum": ["passed", "warning", "failed"],
            },
            "audit_summary": {"type": "string"},
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "category",
                        "severity",
                        "evidence_context",
                        "evidence_draft",
                        "reasoning",
                        "revision_suggestion",
                    ],
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": ["character", "worldview", "timeline", "foreshadowing"],
                        },
                        "severity": {
                            "type": "string",
                            "enum": ["warning", "failed"],
                        },
                        "evidence_context": {"type": "string"},
                        "evidence_draft": {"type": "string"},
                        "reasoning": {"type": "string"},
                        "revision_suggestion": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
            },
        },
        "additionalProperties": True,
    }

    def __init__(
        self,
        *,
        chapter_repo: ChapterRepository,
        report_repo: ConsistencyReportRepository,
        story_context_provider: SQLAlchemyStoryContextProvider,
        text_provider: TextGenerationProvider | None = None,
    ) -> None:
        self.chapter_repo = chapter_repo
        self.report_repo = report_repo
        self.story_context_provider = story_context_provider
        self.text_provider = text_provider
        self._payload_assembler = PromptPayloadAssembler()

    @staticmethod
    def _empty_retrieval_bundle() -> dict[str, Any]:
        return {
            "summary": {"key_facts": [], "current_states": []},
            "items": [],
            "meta": {},
        }

    def run(self, request: ConsistencyReviewRequest) -> ConsistencyReviewResult:
        chapter = self.chapter_repo.get(request.chapter_id)
        if chapter is None:
            raise RuntimeError("chapter 不存在")

        chapter_no_raw = getattr(chapter, "chapter_no", None)
        chapter_no = int(chapter_no_raw) if chapter_no_raw is not None else None
        story_context = self.story_context_provider.load(
            project_id=request.project_id,
            chapter_no=chapter_no,
        )

        chapter_payload = {
            "id": str(chapter.id),
            "chapter_no": chapter_no,
            "title": chapter.title,
            "summary": chapter.summary,
            "content": chapter.content,
        }
        chapter_text = str(chapter.content or "")

        rule_issues = self._run_rule_checks(
            chapter_text=chapter_text,
            chapter_no=chapter_no,
            context=story_context,
        )
        rule_status = self._status_from_issues(rule_issues)

        review_focus = build_review_focus(
            chapter_text=chapter_text,
            chapter_no=chapter_no,
            story_context=story_context,
            rule_issues=rule_issues,
        )
        review_context_slice = build_review_context_slice(
            chapter_text=chapter_text,
            chapter_no=chapter_no,
            story_context=story_context,
            review_focus=review_focus,
            rule_issues=rule_issues,
        )
        review_evidence_pack = build_review_evidence_pack(
            chapter_text=chapter_text,
            chapter_no=chapter_no,
            story_context=story_context,
            review_focus=review_focus,
        )
        review_contract = build_review_contract()
        project_ctx = dict(request.project_snapshot or {})
        if "id" not in project_ctx:
            project_ctx["id"] = str(request.project_id)
        retrieval_bundle = (
            dict(request.retrieval_bundle) if request.retrieval_bundle is not None else self._empty_retrieval_bundle()
        )
        retrieval_bundle = dedupe_retrieval_bundle_against_evidence(
            retrieval_bundle,
            review_context_slice,
        )

        raw_state: dict[str, dict[str, Any]] = {
            "review_contract": {"view": review_contract},
            "review_focus": {"view": review_focus},
            "review_context": {"view": review_context_slice},
            "review_evidence_pack": {"view": review_evidence_pack},
            "chapter_draft_audit": {"view": chapter_payload},
        }
        llm_payload = self._payload_assembler.build(
            role_id=str(request.llm_role_id or self.AGENT_NAME),
            step_key="chapter_audit",
            workflow_type=self.WORKFLOW_NAME,
            project_context=project_ctx,
            raw_state=raw_state,
            retrieval_bundle=retrieval_bundle,
            outline_state={},
        )

        llm_used = False
        llm_status = "passed"
        llm_summary = ""
        llm_issues: list[dict[str, Any]] = []
        if request.llm_enabled and self.text_provider is not None:
            try:
                out_schema = request.llm_response_schema or self.CONSISTENCY_OUTPUT_SCHEMA
                sys_prompt = str(request.llm_system_prompt or self.DEFAULT_SYSTEM_PROMPT)
                tool_loop = env_bool("WRITER_CONSISTENCY_REVIEW_TOOL_LOOP", False)
                if tool_loop and isinstance(self.text_provider, OpenAICompatibleTextProvider):
                    max_fetches = env_int(
                        "WRITER_CONSISTENCY_REVIEW_MAX_FETCHES",
                        3,
                        minimum=1,
                        maximum=20,
                    )
                    strict_entity_fetch = env_bool("WRITER_CONSISTENCY_REVIEW_STRICT_ENTITY_FETCH", True)
                    fetch_allowlist: set[str] | None = None
                    if strict_entity_fetch:
                        fetch_allowlist = collect_review_fetch_allowlist(
                            review_focus=review_focus,
                            review_context_slice=review_context_slice,
                            evidence_pack=review_evidence_pack,
                        )
                    extra_fetch = (
                        "\n\n你可按需调用 fetch_consistency_evidence（scope + entity_id，UUID）"
                        f"补充证据，建议不超过 {max_fetches} 次；"
                        "entity_id 必须已出现在 state.review_context / state.review_evidence_pack 所涉实体中。"
                        if strict_entity_fetch
                        else "\n\n你可按需调用 fetch_consistency_evidence（scope + entity_id，UUID）"
                        f"拉取证据包未包含的实体，建议不超过 {max_fetches} 次；"
                    )
                    sys_prompt = (
                        sys_prompt
                        + extra_fetch
                        + "最后必须调用 consistency_review_output 提交完整审查 JSON。"
                    )

                    def _fetch_evidence(scope: str, entity_id: str) -> dict[str, Any]:
                        return self.story_context_provider.fetch_evidence_entity(
                            project_id=request.project_id,
                            scope=scope,
                            entity_id=entity_id,
                        )

                    cfg = TextGenerationRuntimeConfig.from_env()
                    tool_read_timeout: float | None = None
                    if cfg.revision_llm_timeout_seconds is not None:
                        tool_read_timeout = min(
                            max(float(cfg.revision_llm_timeout_seconds), 1.0),
                            900.0,
                        )

                    llm_result = run_consistency_review_tool_loop(
                        self.text_provider,
                        system_prompt=sys_prompt,
                        user_json=json.dumps(llm_payload, ensure_ascii=False),
                        output_schema=out_schema,
                        output_function_name="consistency_review_output",
                        output_description=(
                            "Return consistency audit JSON with overall_status, audit_summary and issues."
                        ),
                        fetch_handler=_fetch_evidence,
                        max_rounds=6,
                        max_fetches=max_fetches,
                        validation_retries=1,
                        temperature=float(request.llm_temperature or 0.1),
                        max_tokens=int(request.llm_max_tokens or 1200),
                        read_timeout=tool_read_timeout,
                        metadata_tag=str(request.trace_id or "consistency_tool_loop"),
                        entity_id_allowlist=fetch_allowlist,
                    )
                else:
                    llm_result = self.text_provider.generate(
                        TextGenerationRequest(
                            system_prompt=sys_prompt,
                            user_prompt=json.dumps(llm_payload, ensure_ascii=False),
                            temperature=float(request.llm_temperature or 0.1),
                            max_tokens=int(request.llm_max_tokens or 1200),
                            input_payload=llm_payload,
                            input_schema=self.CONSISTENCY_INPUT_SCHEMA,
                            input_schema_name="consistency_review_input",
                            input_schema_strict=True,
                            response_schema=out_schema,
                            response_schema_name="consistency_review_output",
                            response_schema_strict=True,
                            validation_retries=1,
                            use_function_calling=True,
                            function_name="consistency_review_output",
                            function_description=(
                                "Return consistency audit JSON with overall_status, audit_summary and issues."
                            ),
                            metadata_json={
                                "workflow": self.WORKFLOW_NAME,
                                "trace_id": request.trace_id,
                                "role_id": request.llm_role_id,
                                "strategy_version": request.llm_strategy_version,
                                "prompt_hash": request.llm_prompt_hash,
                                "schema_ref": request.llm_schema_ref,
                            },
                        )
                    )
                llm_used = True
                llm_output = dict(llm_result.json_data or {})
                llm_status = self._normalize_status(llm_output.get("overall_status"))
                llm_summary = str(llm_output.get("audit_summary") or "").strip()
                llm_issues = self._normalize_llm_issues(list(llm_output.get("issues") or []))
            except Exception:
                llm_used = False

        merged_issues = self._merge_issues(rule_issues, llm_issues)
        merged_status = self._max_status(
            [
                rule_status,
                (llm_status if llm_used else "passed"),
                self._status_from_issues(merged_issues),
            ]
        )
        summary = self._build_summary(
            status=merged_status,
            rule_issues=rule_issues,
            llm_summary=llm_summary,
        )
        recommendations = self._build_recommendations(merged_issues)
        score = self._status_to_score(merged_status)

        row = self.report_repo.create_report(
            project_id=request.project_id,
            chapter_id=chapter.id,
            chapter_version_id=request.chapter_version_id,
            status=merged_status,
            score=score,
            summary=summary,
            issues_json=merged_issues,
            recommendations_json=recommendations,
            source_agent=(request.llm_role_id if llm_used else "consistency_rule_engine"),
            source_workflow=self.WORKFLOW_NAME,
            trace_id=request.trace_id,
        )
        return ConsistencyReviewResult(
            report_id=str(row.id),
            status=str(row.status),
            score=float(row.score) if row.score is not None else None,
            summary=str(row.summary or ""),
            issues=list(row.issues_json or []),
            recommendations=list(row.recommendations_json or []),
            llm_used=bool(llm_used),
            rule_issues_count=len(rule_issues),
            llm_issues_count=len(llm_issues),
        )

    def _run_rule_checks(
        self,
        *,
        chapter_text: str,
        chapter_no: int | None,
        context: StoryConstraintContext,
    ) -> list[dict[str, Any]]:
        text = str(chapter_text or "")
        if not text.strip():
            return [
                self._make_issue(
                    category="timeline",
                    severity="failed",
                    evidence_context="章节正文为空。",
                    evidence_draft="(empty)",
                    reasoning="无正文时无法保证角色、时间线与设定一致性。",
                    revision_suggestion="补全正文后再进行一致性审查。",
                    source="rule",
                )
            ]

        issues: list[dict[str, Any]] = []
        issues.extend(self._check_timeline_leak(text=text, chapter_no=chapter_no, context=context))
        issues.extend(self._check_foreshadowing_payoff(text=text, chapter_no=chapter_no, context=context))
        issues.extend(self._check_character_constraints(text=text, context=context))
        issues.extend(self._check_world_constraints(text=text, context=context))
        return issues

    def _check_timeline_leak(
        self,
        *,
        text: str,
        chapter_no: int | None,
        context: StoryConstraintContext,
    ) -> list[dict[str, Any]]:
        if chapter_no is None:
            return []
        out: list[dict[str, Any]] = []
        for event in list(context.timeline_events or []):
            event_ch_no = event.get("chapter_no")
            if event_ch_no is None:
                continue
            try:
                event_ch_no_int = int(event_ch_no)
            except (TypeError, ValueError):
                continue
            if event_ch_no_int <= chapter_no:
                continue
            event_title = str(event.get("event_title") or "").strip()
            event_desc = str(event.get("event_desc") or "").strip()
            trigger_terms = [term for term in [event_title, event_desc] if len(term) >= 4]
            matched = next((term for term in trigger_terms if term in text), None)
            if not matched:
                continue
            out.append(
                self._make_issue(
                    category="timeline",
                    severity="failed",
                    evidence_context=(
                        f"时间线事件（第{event_ch_no_int}章）: "
                        f"{self._clip(event_title or event_desc, 140)}"
                    ),
                    evidence_draft=f"当前草稿出现未来事件片段: {self._clip(matched, 140)}",
                    reasoning="当前章节引用了未来章节已定义事件，存在时间线提前泄露。",
                    revision_suggestion="将该事件改写为伏笔或删除直接结果描述，避免越章透出。",
                    source="rule",
                )
            )
        return out

    def _check_foreshadowing_payoff(
        self,
        *,
        text: str,
        chapter_no: int | None,
        context: StoryConstraintContext,
    ) -> list[dict[str, Any]]:
        if chapter_no is None:
            return []
        out: list[dict[str, Any]] = []
        for item in list(context.foreshadowings or []):
            payoff_ch = item.get("payoff_chapter_no")
            if payoff_ch is None:
                continue
            try:
                payoff_ch_int = int(payoff_ch)
            except (TypeError, ValueError):
                continue
            if payoff_ch_int <= chapter_no:
                continue

            payoff_text = str(item.get("payoff_text") or "").strip()
            if len(payoff_text) < 4:
                continue
            if payoff_text not in text:
                continue

            setup = str(item.get("setup_text") or "").strip()
            out.append(
                self._make_issue(
                    category="foreshadowing",
                    severity="failed",
                    evidence_context=(
                        f"伏笔设定（预计第{payoff_ch_int}章回收）: "
                        f"{self._clip(setup or payoff_text, 140)}"
                    ),
                    evidence_draft=f"当前草稿已提前回收伏笔: {self._clip(payoff_text, 140)}",
                    reasoning="伏笔在计划回收章节之前被直接兑现，会破坏叙事节奏。",
                    revision_suggestion="将该处改为暗示或误导，不直接给出最终回收信息。",
                    source="rule",
                )
            )
        return out

    def _check_character_constraints(self, *, text: str, context: StoryConstraintContext) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for character in list(context.characters or []):
            name = str(character.get("name") or "").strip()
            if not name or name not in text:
                continue
            profile = dict(character.get("profile_json") or {})
            taboo_terms: list[str] = []
            for key in ("forbidden_behaviors", "must_not", "taboos"):
                taboo_terms.extend([str(x).strip() for x in list(profile.get(key) or []) if str(x).strip()])
            if not taboo_terms:
                continue
            matched = next((term for term in taboo_terms if term and term in text), None)
            if not matched:
                continue
            out.append(
                self._make_issue(
                    category="character",
                    severity="warning",
                    evidence_context=f"{name} 角色约束禁项: {self._clip(matched, 120)}",
                    evidence_draft=f"草稿命中禁项描述: {self._clip(matched, 120)}",
                    reasoning="角色行为触发了已定义的禁项，可能导致人设偏移。",
                    revision_suggestion=f"保留剧情目标但调整 {name} 的行为表达，避免触发禁项。",
                    source="rule",
                )
            )
        return out

    def _check_world_constraints(self, *, text: str, context: StoryConstraintContext) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for entry in list(context.world_entries or []):
            title = str(entry.get("title") or "").strip()
            content = str(entry.get("content") or "").strip()
            metadata = dict(entry.get("metadata_json") or {})
            forbidden_terms: list[str] = []
            for key in ("forbidden_terms", "forbidden_words", "ban_terms"):
                forbidden_terms.extend([str(x).strip() for x in list(metadata.get(key) or []) if str(x).strip()])
            if not forbidden_terms:
                continue
            matched = next((term for term in forbidden_terms if term and term in text), None)
            if not matched:
                continue
            out.append(
                self._make_issue(
                    category="worldview",
                    severity="failed",
                    evidence_context=f"{self._clip(title or content, 140)} 的禁用项: {self._clip(matched, 120)}",
                    evidence_draft=f"草稿出现禁用世界观元素: {self._clip(matched, 120)}",
                    reasoning="草稿命中世界观显式禁用项，属于硬规则冲突。",
                    revision_suggestion="替换为已存在的可用设定，或补充规则来源并调整为可解释行为。",
                    source="rule",
                )
            )
        return out

    def _normalize_llm_issues(self, issues: list[Any]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in issues:
            if not isinstance(item, dict):
                continue
            category = self._normalize_category(item.get("category"))
            severity = self._normalize_severity(item.get("severity"))
            evidence_context = str(item.get("evidence_context") or "").strip()
            evidence_draft = str(item.get("evidence_draft") or "").strip()
            reasoning = str(item.get("reasoning") or "").strip()
            revision_suggestion = str(item.get("revision_suggestion") or "").strip()
            if not any([evidence_context, evidence_draft, reasoning, revision_suggestion]):
                continue
            normalized.append(
                self._make_issue(
                    category=category,
                    severity=severity,
                    evidence_context=evidence_context or "（LLM 未提供）",
                    evidence_draft=evidence_draft or "（LLM 未提供）",
                    reasoning=reasoning or "（LLM 未提供）",
                    revision_suggestion=revision_suggestion or "结合上下文补充具体修订建议。",
                    source="llm",
                )
            )
        return normalized

    def _merge_issues(
        self,
        rule_issues: list[dict[str, Any]],
        llm_issues: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for issue in list(rule_issues) + list(llm_issues):
            category = self._normalize_category(issue.get("category"))
            draft = self._clip(str(issue.get("evidence_draft") or ""), 160)
            reasoning = self._clip(str(issue.get("reasoning") or ""), 160)
            key = (category, draft, reasoning)
            if key in seen:
                continue
            seen.add(key)
            merged.append(
                {
                    **dict(issue),
                    "category": category,
                    "severity": self._normalize_severity(issue.get("severity")),
                }
            )
        return merged

    @staticmethod
    def _build_recommendations(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for idx, issue in enumerate(issues, start=1):
            suggestion = str(issue.get("revision_suggestion") or "").strip()
            if not suggestion or suggestion in seen:
                continue
            seen.add(suggestion)
            out.append(
                {
                    "priority": idx,
                    "category": str(issue.get("category") or "timeline"),
                    "severity": str(issue.get("severity") or "warning"),
                    "action": suggestion,
                    "source": str(issue.get("source") or "rule"),
                }
            )
        return out

    def _build_summary(
        self,
        *,
        status: str,
        rule_issues: list[dict[str, Any]],
        llm_summary: str,
    ) -> str:
        if llm_summary:
            return llm_summary
        if status == "passed":
            return "未发现明显一致性冲突。"
        if not rule_issues:
            return "检测到潜在一致性风险，请结合问题清单修订。"
        categories = [str(item.get("category") or "") for item in rule_issues]
        category_text = "、".join(sorted({c for c in categories if c}))
        return (
            f"规则审查发现 {len(rule_issues)} 个问题"
            + (f"（涉及 {category_text}）" if category_text else "")
            + "，建议先修正硬冲突再润色。"
        )

    @staticmethod
    def _status_to_score(status: str) -> float:
        normalized = str(status or "warning").strip().lower()
        if normalized == "passed":
            return 1.0
        if normalized == "failed":
            return 0.2
        return 0.65

    def _status_from_issues(self, issues: list[dict[str, Any]]) -> str:
        if not issues:
            return "passed"
        severities = [self._normalize_severity(item.get("severity")) for item in issues]
        if "failed" in severities:
            return "failed"
        return "warning"

    def _max_status(self, statuses: list[str]) -> str:
        order = {"passed": 0, "warning": 1, "failed": 2}
        best = "passed"
        best_value = -1
        for raw in statuses:
            status = self._normalize_status(raw)
            value = order.get(status, 1)
            if value > best_value:
                best_value = value
                best = status
        return best

    @staticmethod
    def _normalize_status(raw: Any) -> str:
        value = str(raw or "").strip().lower()
        if value in {"passed", "warning", "failed"}:
            return value
        return "warning"

    @staticmethod
    def _normalize_severity(raw: Any) -> str:
        value = str(raw or "").strip().lower()
        if value == "failed":
            return "failed"
        return "warning"

    @staticmethod
    def _normalize_category(raw: Any) -> str:
        value = str(raw or "").strip().lower()
        mapping = {
            "character": "character",
            "worldview": "worldview",
            "world": "worldview",
            "timeline": "timeline",
            "foreshadowing": "foreshadowing",
        }
        return mapping.get(value, "timeline")

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        raw = str(text or "").strip()
        if len(raw) <= limit:
            return raw
        return raw[: max(1, limit - 3)] + "..."

    def _make_issue(
        self,
        *,
        category: str,
        severity: str,
        evidence_context: str,
        evidence_draft: str,
        reasoning: str,
        revision_suggestion: str,
        source: str,
    ) -> dict[str, Any]:
        return {
            "category": self._normalize_category(category),
            "severity": self._normalize_severity(severity),
            "evidence_context": str(evidence_context or "").strip(),
            "evidence_draft": str(evidence_draft or "").strip(),
            "reasoning": str(reasoning or "").strip(),
            "revision_suggestion": str(revision_suggestion or "").strip(),
            "source": str(source or "rule"),
        }
