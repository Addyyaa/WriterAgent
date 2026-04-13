from __future__ import annotations

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.retrieval_evidence_item import RetrievalEvidenceItem
from packages.storage.postgres.models.retrieval_round import RetrievalRound


class RetrievalTraceRepository(BaseRepository):
    """检索轮次与证据回放仓储。"""

    def create_round(
        self,
        *,
        workflow_run_id,
        workflow_step_id,
        project_id,
        trace_id: str | None,
        retrieval_trace_id: str,
        step_key: str,
        workflow_type: str,
        round_index: int,
        query: str,
        intent: str | None,
        source_types_json: list[str] | None,
        time_scope_json: dict | None,
        chapter_window_json: dict | None,
        must_have_slots_json: list[str] | None,
        enough_context: bool,
        coverage_score: float,
        new_evidence_gain: float,
        stop_reason: str | None,
        latency_ms: int | None,
        decision_json: dict | None,
        auto_commit: bool = True,
    ) -> RetrievalRound:
        row = RetrievalRound(
            workflow_run_id=workflow_run_id,
            workflow_step_id=workflow_step_id,
            project_id=project_id,
            trace_id=trace_id,
            retrieval_trace_id=retrieval_trace_id,
            step_key=step_key,
            workflow_type=workflow_type,
            round_index=max(1, int(round_index)),
            query=str(query or "").strip(),
            intent=str(intent).strip() if intent else None,
            source_types_json=list(source_types_json or []),
            time_scope_json=dict(time_scope_json or {}),
            chapter_window_json=dict(chapter_window_json or {}),
            must_have_slots_json=list(must_have_slots_json or []),
            enough_context=bool(enough_context),
            coverage_score=float(coverage_score),
            new_evidence_gain=float(new_evidence_gain),
            stop_reason=str(stop_reason).strip() if stop_reason else None,
            latency_ms=int(latency_ms) if latency_ms is not None else None,
            decision_json=dict(decision_json or {}),
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def create_evidence_items(
        self,
        *,
        retrieval_round_id,
        workflow_run_id,
        workflow_step_id,
        project_id,
        trace_id: str | None,
        retrieval_trace_id: str,
        step_key: str,
        round_index: int,
        items: list[dict],
        auto_commit: bool = True,
    ) -> list[RetrievalEvidenceItem]:
        created: list[RetrievalEvidenceItem] = []
        for item in items:
            row = RetrievalEvidenceItem(
                retrieval_round_id=retrieval_round_id,
                workflow_run_id=workflow_run_id,
                workflow_step_id=workflow_step_id,
                project_id=project_id,
                trace_id=trace_id,
                retrieval_trace_id=retrieval_trace_id,
                step_key=step_key,
                round_index=max(1, int(round_index)),
                source_type=str(item.get("source_type") or "unknown"),
                source_id=(str(item.get("source_id")) if item.get("source_id") is not None else None),
                chunk_id=(str(item.get("chunk_id")) if item.get("chunk_id") is not None else None),
                score=(float(item.get("score")) if item.get("score") is not None else None),
                adopted=bool(item.get("adopted", True)),
                evidence_text=str(item.get("text") or "").strip(),
                metadata_json=dict(item.get("metadata_json") or {}),
            )
            self.db.add(row)
            created.append(row)

        if auto_commit:
            self.db.commit()
            for row in created:
                self.db.refresh(row)
        else:
            self.db.flush()
        return created

    def list_rounds_by_run(self, *, workflow_run_id, limit: int = 500) -> list[RetrievalRound]:
        stmt = (
            select(RetrievalRound)
            .where(RetrievalRound.workflow_run_id == workflow_run_id)
            .order_by(RetrievalRound.created_at.asc(), RetrievalRound.id.asc())
            .limit(max(1, int(limit)))
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_evidence_by_run(self, *, workflow_run_id, limit: int = 4000) -> list[RetrievalEvidenceItem]:
        stmt = (
            select(RetrievalEvidenceItem)
            .where(RetrievalEvidenceItem.workflow_run_id == workflow_run_id)
            .order_by(
                RetrievalEvidenceItem.round_index.asc(),
                RetrievalEvidenceItem.id.asc(),
            )
            .limit(max(1, int(limit)))
        )
        return list(self.db.execute(stmt).scalars().all())
