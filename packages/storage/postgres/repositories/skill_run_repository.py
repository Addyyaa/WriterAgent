from __future__ import annotations

from typing import Any

from sqlalchemy import inspect, select

from .base import BaseRepository
from packages.storage.postgres.models.skill_evidence import SkillEvidence
from packages.storage.postgres.models.skill_finding import SkillFinding
from packages.storage.postgres.models.skill_metric import SkillMetric
from packages.storage.postgres.models.skill_run import SkillRun


class SkillRunRepository(BaseRepository):
    def __init__(self, db):
        super().__init__(db)
        self._dual_write_enabled = self._detect_dual_write_tables()

    def create_run(
        self,
        *,
        trace_id: str,
        agent_run_id,
        skill_name: str,
        skill_version: str | None = None,
        role_id: str | None = None,
        strategy_version: str | None = None,
        prompt_hash: str | None = None,
        schema_version: str | None = None,
        input_snapshot_json: dict | None = None,
        auto_commit: bool = True,
    ) -> SkillRun:
        row = SkillRun(
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            skill_name=skill_name,
            skill_version=skill_version,
            role_id=role_id,
            strategy_version=strategy_version,
            prompt_hash=prompt_hash,
            schema_version=schema_version,
            input_snapshot_json=input_snapshot_json or {},
            output_snapshot_json={},
            status="pending",
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def get(self, run_id) -> SkillRun | None:
        return self.db.get(SkillRun, run_id)

    def start(self, run_id, *, auto_commit: bool = True) -> SkillRun | None:
        row = self.get(run_id)
        if row is None:
            return None
        row.status = "running"
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def succeed(
        self,
        run_id,
        *,
        output_snapshot_json: dict | None = None,
        auto_commit: bool = True,
    ) -> SkillRun | None:
        row = self.get(run_id)
        if row is None:
            return None
        row.status = "success"
        if output_snapshot_json is not None:
            row.output_snapshot_json = output_snapshot_json
            self._write_artifact_tables(row=row, snapshot=output_snapshot_json)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def fail(
        self,
        run_id,
        *,
        output_snapshot_json: dict | None = None,
        auto_commit: bool = True,
    ) -> SkillRun | None:
        row = self.get(run_id)
        if row is None:
            return None
        row.status = "failed"
        if output_snapshot_json is not None:
            row.output_snapshot_json = output_snapshot_json
            self._write_artifact_tables(row=row, snapshot=output_snapshot_json)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def list_by_agent_run(self, *, agent_run_id, limit: int = 200) -> list[SkillRun]:
        if limit <= 0:
            return []
        stmt = (
            select(SkillRun)
            .where(SkillRun.agent_run_id == agent_run_id)
            .order_by(SkillRun.created_at.asc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def _write_artifact_tables(self, *, row: SkillRun, snapshot: dict[str, Any]) -> None:
        if not self._dual_write_enabled:
            return
        payload = dict(snapshot or {})
        if not payload:
            return

        # 幂等：同一个 run 反复写入时覆盖旧记录。
        self.db.query(SkillFinding).filter(SkillFinding.skill_run_id == row.id).delete(synchronize_session=False)
        self.db.query(SkillEvidence).filter(SkillEvidence.skill_run_id == row.id).delete(synchronize_session=False)
        self.db.query(SkillMetric).filter(SkillMetric.skill_run_id == row.id).delete(synchronize_session=False)

        findings = self._extract_findings(payload)
        evidence = self._extract_evidence(payload)
        metrics = self._extract_metrics(payload)
        phases = self._extract_phases(payload)

        for item in findings:
            self.db.add(
                SkillFinding(
                    skill_run_id=row.id,
                    trace_id=row.trace_id,
                    agent_run_id=row.agent_run_id,
                    skill_name=str(payload.get("skill_id") or row.skill_name or ""),
                    phase=str(item.get("phase") or ""),
                    finding_type=str(item.get("type") or ""),
                    severity=str(item.get("severity") or "info"),
                    message=str(item.get("message") or item.get("title") or "skill finding"),
                    evidence_json=dict(item.get("evidence") or {}),
                )
            )

        for item in evidence:
            self.db.add(
                SkillEvidence(
                    skill_run_id=row.id,
                    trace_id=row.trace_id,
                    agent_run_id=row.agent_run_id,
                    skill_name=str(payload.get("skill_id") or row.skill_name or ""),
                    phase=str(item.get("phase") or ""),
                    source_scope=str(item.get("source_scope") or ""),
                    evidence_type=str(item.get("type") or ""),
                    payload_json=dict(item.get("payload") or {}),
                )
            )

        for metric_key, metric_value in metrics.items():
            numeric_value = None
            if isinstance(metric_value, (int, float)) and not isinstance(metric_value, bool):
                numeric_value = float(metric_value)
            self.db.add(
                SkillMetric(
                    skill_run_id=row.id,
                    trace_id=row.trace_id,
                    agent_run_id=row.agent_run_id,
                    skill_name=str(payload.get("skill_id") or row.skill_name or ""),
                    phase=str(metric_value.get("phase") or "")
                    if isinstance(metric_value, dict)
                    else "",
                    metric_key=str(metric_key),
                    metric_value=numeric_value,
                    metric_json=(dict(metric_value) if isinstance(metric_value, dict) else {"value": metric_value}),
                )
            )

        for phase in phases:
            phase_name = str(phase.get("phase") or "").strip()
            phase_metrics = dict(phase.get("metrics") or {})
            for metric_key, metric_value in phase_metrics.items():
                namespaced_key = f"{phase_name}.{metric_key}" if phase_name else str(metric_key)
                numeric_value = None
                if isinstance(metric_value, (int, float)) and not isinstance(metric_value, bool):
                    numeric_value = float(metric_value)
                self.db.add(
                    SkillMetric(
                        skill_run_id=row.id,
                        trace_id=row.trace_id,
                        agent_run_id=row.agent_run_id,
                        skill_name=str(payload.get("skill_id") or row.skill_name or ""),
                        phase=phase_name,
                        metric_key=namespaced_key,
                        metric_value=numeric_value,
                        metric_json=(
                            dict(metric_value) if isinstance(metric_value, dict) else {"value": metric_value}
                        ),
                    )
                )

    @staticmethod
    def _extract_findings(payload: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for candidate in list(payload.get("findings") or []):
            if isinstance(candidate, dict):
                items.append(dict(candidate))
        for phase in list(payload.get("phases") or []):
            if not isinstance(phase, dict):
                continue
            phase_name = str(phase.get("phase") or "").strip()
            for candidate in list(phase.get("findings") or []):
                if not isinstance(candidate, dict):
                    continue
                item = dict(candidate)
                item.setdefault("phase", phase_name)
                items.append(item)
        return items

    @staticmethod
    def _extract_evidence(payload: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for candidate in list(payload.get("evidence") or []):
            if isinstance(candidate, dict):
                items.append(dict(candidate))
        for phase in list(payload.get("phases") or []):
            if not isinstance(phase, dict):
                continue
            phase_name = str(phase.get("phase") or "").strip()
            for candidate in list(phase.get("evidence") or []):
                if not isinstance(candidate, dict):
                    continue
                item = dict(candidate)
                item.setdefault("phase", phase_name)
                items.append(item)
        return items

    @staticmethod
    def _extract_metrics(payload: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        metrics = payload.get("metrics")
        if isinstance(metrics, dict):
            merged.update(dict(metrics))
        elif isinstance(metrics, list):
            for item in metrics:
                if isinstance(item, dict):
                    key = str(item.get("key") or item.get("name") or "").strip()
                    if key:
                        merged[key] = item.get("value")
        merged.setdefault("effective_delta", payload.get("effective_delta", 0))
        merged.setdefault("fallback_used", bool(payload.get("fallback_used", False)))
        return merged

    @staticmethod
    def _extract_phases(payload: dict[str, Any]) -> list[dict[str, Any]]:
        phases = payload.get("phases")
        if not isinstance(phases, list):
            return []
        return [dict(item) for item in phases if isinstance(item, dict)]

    def _detect_dual_write_tables(self) -> bool:
        bind = self.db.get_bind()
        if bind is None:
            return False
        inspector = inspect(bind)
        try:
            return all(
                inspector.has_table(name)
                for name in ("skill_findings", "skill_evidence", "skill_metrics")
            )
        except Exception:
            return False
