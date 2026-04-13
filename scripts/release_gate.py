"""本地发布门禁脚本（迁移 + 测试 + 指标阈值）。

示例：
    ./venv/bin/python scripts/release_gate.py

可选：
    ./venv/bin/python scripts/release_gate.py --skip-integration
    ./venv/bin/python scripts/release_gate.py --allow-missing-metrics
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class GateThresholds:
    max_empty_result_rate: float
    min_fallback_hit_rate: float
    max_embedding_failure_rate: float
    max_retrieval_p95_ms: float
    min_retrieval_replay_completeness: float
    min_evidence_coverage: float
    max_consistency_conflict_rate: float
    min_revision_gain_rate: float
    min_backup_last_success: float
    min_restore_drill_last_success: float


@dataclass(frozen=True)
class ObservedMetrics:
    empty_result_rate: float | None
    fallback_hit_rate: float | None
    embedding_failure_rate: float | None
    retrieval_p95_ms: float | None
    retrieval_replay_completeness: float | None
    evidence_coverage: float | None
    consistency_conflict_rate: float | None
    revision_gain_rate: float | None
    backup_last_success: float | None
    restore_drill_last_success: float | None


def main() -> int:
    parser = argparse.ArgumentParser(description="WriterAgent 本地发布门禁")
    parser.add_argument("--skip-tests", action="store_true", help="跳过全部测试")
    parser.add_argument("--skip-integration", action="store_true", help="跳过集成脚本")
    parser.add_argument(
        "--allow-missing-metrics",
        action="store_true",
        help="允许缺失在线指标（默认缺失即失败）",
    )
    args = parser.parse_args()

    python_exe = _resolve_python()
    alembic_exe = _resolve_alembic()

    print("[gate] 1/3 migration check")
    _check_migration_head(alembic_exe)

    if not args.skip_tests:
        print("[gate] 2/3 test check")
        _run_tests(python_exe, skip_integration=args.skip_integration)
    else:
        print("[gate] 2/3 test check skipped")

    print("[gate] 3/3 metrics threshold check")
    _check_metric_thresholds(allow_missing=args.allow_missing_metrics)

    print("[gate] PASS")
    return 0


def _resolve_python() -> str:
    venv_python = PROJECT_ROOT / "venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _resolve_alembic() -> str:
    venv_alembic = PROJECT_ROOT / "venv" / "bin" / "alembic"
    if venv_alembic.exists():
        return str(venv_alembic)
    return "alembic"


def _run(cmd: list[str]) -> str:
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        out = proc.stdout.strip()
        err = proc.stderr.strip()
        raise RuntimeError(
            f"命令失败: {' '.join(cmd)}\nstdout:\n{out}\nstderr:\n{err}"
        )
    return proc.stdout.strip()


def _check_migration_head(alembic_exe: str) -> None:
    current_raw = _run([alembic_exe, "current"])
    heads_raw = _run([alembic_exe, "heads"])

    current_ids = _extract_revision_ids(current_raw)
    head_ids = _extract_revision_ids(heads_raw)

    if not head_ids:
        raise RuntimeError("无法解析 alembic heads，请检查迁移配置")
    if not current_ids:
        raise RuntimeError("无法解析 alembic current，请先执行 alembic upgrade head")

    current_last = current_ids[-1]
    if current_last not in head_ids:
        raise RuntimeError(
            "数据库迁移未到最新。"
            f" current={current_last}, heads={','.join(head_ids)}"
        )


def _extract_revision_ids(text: str) -> list[str]:
    return re.findall(r"\b[0-9a-f]{12}\b", text.lower())


def _run_tests(python_exe: str, *, skip_integration: bool) -> None:
    commands: list[list[str]] = [
        [python_exe, "-m", "unittest", "discover", "-s", "tests/unit", "-p", "test_*.py", "-v"],
        [python_exe, "-m", "unittest", "tests.unit.test_retrieval_loop_service", "-v"],
        [python_exe, "scripts/test_retrieval_pipeline_contract.py"],
    ]
    if not skip_integration:
        commands.extend(
            [
                [python_exe, "scripts/test_memory_ingestion_service.py"],
                [python_exe, "scripts/test_memory_dedup_pipeline.py"],
                [python_exe, "scripts/test_memory_search_service.py"],
                [python_exe, "scripts/test_memory_forgetting_service.py"],
                [python_exe, "scripts/test_chapter_generation_workflow.py"],
                [python_exe, "scripts/test_chapter_generation_api.py"],
                [python_exe, "scripts/test_writing_orchestrator_workflow.py"],
                [python_exe, "scripts/test_writing_orchestrator_api.py"],
            ]
        )

    for cmd in commands:
        print(f"[gate:test] running: {' '.join(cmd)}")
        _run(cmd)


def _check_metric_thresholds(*, allow_missing: bool) -> None:
    thresholds = GateThresholds(
        max_empty_result_rate=_env_float("WRITER_GATE_MAX_EMPTY_RESULT_RATE", 0.35),
        min_fallback_hit_rate=_env_float("WRITER_GATE_MIN_FALLBACK_HIT_RATE", 0.02),
        max_embedding_failure_rate=_env_float("WRITER_GATE_MAX_EMBEDDING_FAILURE_RATE", 0.05),
        max_retrieval_p95_ms=_env_float("WRITER_GATE_MAX_RETRIEVAL_P95_MS", 1500.0),
        min_retrieval_replay_completeness=_env_float("WRITER_GATE_MIN_RETRIEVAL_REPLAY_COMPLETENESS", 0.95),
        min_evidence_coverage=_env_float("WRITER_GATE_MIN_EVIDENCE_COVERAGE", 0.80),
        max_consistency_conflict_rate=_env_float("WRITER_GATE_MAX_CONSISTENCY_CONFLICT_RATE", 0.30),
        min_revision_gain_rate=_env_float("WRITER_GATE_MIN_REVISION_GAIN_RATE", 0.05),
        min_backup_last_success=_env_float("WRITER_GATE_MIN_BACKUP_LAST_SUCCESS", 1.0),
        min_restore_drill_last_success=_env_float("WRITER_GATE_MIN_RESTORE_DRILL_LAST_SUCCESS", 1.0),
    )
    observed = ObservedMetrics(
        empty_result_rate=_env_float_or_none("WRITER_METRIC_EMPTY_RESULT_RATE"),
        fallback_hit_rate=_env_float_or_none("WRITER_METRIC_FALLBACK_HIT_RATE"),
        embedding_failure_rate=_env_float_or_none("WRITER_METRIC_EMBEDDING_FAILURE_RATE"),
        retrieval_p95_ms=_env_float_or_none("WRITER_METRIC_RETRIEVAL_P95_MS"),
        retrieval_replay_completeness=_env_float_or_none("WRITER_METRIC_RETRIEVAL_REPLAY_COMPLETENESS"),
        evidence_coverage=_env_float_or_none("WRITER_METRIC_EVIDENCE_COVERAGE"),
        consistency_conflict_rate=_env_float_or_none("WRITER_METRIC_CONSISTENCY_CONFLICT_RATE"),
        revision_gain_rate=_env_float_or_none("WRITER_METRIC_REVISION_GAIN_RATE"),
        backup_last_success=_env_float_or_none("WRITER_METRIC_BACKUP_LAST_SUCCESS"),
        restore_drill_last_success=_env_float_or_none("WRITER_METRIC_RESTORE_DRILL_LAST_SUCCESS"),
    )

    missing: list[str] = []
    if observed.empty_result_rate is None:
        missing.append("WRITER_METRIC_EMPTY_RESULT_RATE")
    if observed.fallback_hit_rate is None:
        missing.append("WRITER_METRIC_FALLBACK_HIT_RATE")
    if observed.embedding_failure_rate is None:
        missing.append("WRITER_METRIC_EMBEDDING_FAILURE_RATE")
    if observed.retrieval_p95_ms is None:
        missing.append("WRITER_METRIC_RETRIEVAL_P95_MS")
    if observed.retrieval_replay_completeness is None:
        missing.append("WRITER_METRIC_RETRIEVAL_REPLAY_COMPLETENESS")
    if observed.evidence_coverage is None:
        missing.append("WRITER_METRIC_EVIDENCE_COVERAGE")
    if observed.consistency_conflict_rate is None:
        missing.append("WRITER_METRIC_CONSISTENCY_CONFLICT_RATE")
    if observed.revision_gain_rate is None:
        missing.append("WRITER_METRIC_REVISION_GAIN_RATE")
    if observed.backup_last_success is None:
        missing.append("WRITER_METRIC_BACKUP_LAST_SUCCESS")
    if observed.restore_drill_last_success is None:
        missing.append("WRITER_METRIC_RESTORE_DRILL_LAST_SUCCESS")

    if missing and not allow_missing:
        raise RuntimeError(
            "缺少指标输入，无法执行门禁阈值检查：" + ", ".join(missing)
        )
    if missing and allow_missing:
        print("[gate:metric] missing metrics ignored:", ", ".join(missing))
        return

    assert observed.empty_result_rate is not None
    assert observed.fallback_hit_rate is not None
    assert observed.embedding_failure_rate is not None
    assert observed.retrieval_p95_ms is not None
    assert observed.retrieval_replay_completeness is not None
    assert observed.evidence_coverage is not None
    assert observed.consistency_conflict_rate is not None
    assert observed.revision_gain_rate is not None
    assert observed.backup_last_success is not None
    assert observed.restore_drill_last_success is not None

    failures: list[str] = []
    if observed.empty_result_rate > thresholds.max_empty_result_rate:
        failures.append(
            f"empty_result_rate 超阈值: {observed.empty_result_rate:.4f} > {thresholds.max_empty_result_rate:.4f}"
        )
    if observed.fallback_hit_rate < thresholds.min_fallback_hit_rate:
        failures.append(
            f"fallback_hit_rate 低于阈值: {observed.fallback_hit_rate:.4f} < {thresholds.min_fallback_hit_rate:.4f}"
        )
    if observed.embedding_failure_rate > thresholds.max_embedding_failure_rate:
        failures.append(
            f"embedding_failure_rate 超阈值: {observed.embedding_failure_rate:.4f} > {thresholds.max_embedding_failure_rate:.4f}"
        )
    if observed.retrieval_p95_ms > thresholds.max_retrieval_p95_ms:
        failures.append(
            f"retrieval_p95_ms 超阈值: {observed.retrieval_p95_ms:.2f} > {thresholds.max_retrieval_p95_ms:.2f}"
        )
    if observed.retrieval_replay_completeness < thresholds.min_retrieval_replay_completeness:
        failures.append(
            "retrieval_replay_completeness 低于阈值: "
            f"{observed.retrieval_replay_completeness:.4f} < {thresholds.min_retrieval_replay_completeness:.4f}"
        )
    if observed.evidence_coverage < thresholds.min_evidence_coverage:
        failures.append(
            f"evidence_coverage 低于阈值: {observed.evidence_coverage:.4f} < {thresholds.min_evidence_coverage:.4f}"
        )
    if observed.consistency_conflict_rate > thresholds.max_consistency_conflict_rate:
        failures.append(
            "consistency_conflict_rate 超阈值: "
            f"{observed.consistency_conflict_rate:.4f} > {thresholds.max_consistency_conflict_rate:.4f}"
        )
    if observed.revision_gain_rate < thresholds.min_revision_gain_rate:
        failures.append(
            f"revision_gain_rate 低于阈值: {observed.revision_gain_rate:.4f} < {thresholds.min_revision_gain_rate:.4f}"
        )
    if observed.backup_last_success < thresholds.min_backup_last_success:
        failures.append(
            f"backup_last_success 低于阈值: {observed.backup_last_success:.4f} < {thresholds.min_backup_last_success:.4f}"
        )
    if observed.restore_drill_last_success < thresholds.min_restore_drill_last_success:
        failures.append(
            "restore_drill_last_success 低于阈值: "
            f"{observed.restore_drill_last_success:.4f} < {thresholds.min_restore_drill_last_success:.4f}"
        )

    if failures:
        raise RuntimeError("门禁失败:\n- " + "\n- ".join(failures))



def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _env_float_or_none(name: str) -> float | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    try:
        return float(raw.strip())
    except ValueError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
