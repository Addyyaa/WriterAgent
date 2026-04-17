"""workflow_step_repository 重试相关行为的单元测试。"""
from __future__ import annotations

from unittest.mock import MagicMock

from packages.storage.postgres.repositories.workflow_step_repository import (
    WorkflowStepRepository,
)


class _StubStep:
    def __init__(self, status: str) -> None:
        self.status = status
        self.error_code = "ec"
        self.error_message = "em"
        self.started_at = object()
        self.finished_at = object()
        self.output_json: dict = {"old": True}
        self.heartbeat_at = object()
        self.last_progress_at = object()


class _RepoForRetryTest(WorkflowStepRepository):
    """仅覆盖 list_by_run，避免单测依赖真实数据库。"""

    def __init__(self, steps: list[_StubStep]) -> None:
        super().__init__(MagicMock())
        self._steps = steps

    def list_by_run(self, *, workflow_run_id):  # type: ignore[override]
        return self._steps


def test_reset_for_retry_turns_cancelled_and_failed_into_pending() -> None:
    steps = [
        _StubStep("success"),
        _StubStep("cancelled"),
        _StubStep("failed"),
    ]
    repo = _RepoForRetryTest(steps)
    count = repo.reset_for_retry(workflow_run_id="00000000-0000-0000-0000-000000000001", auto_commit=False)
    assert count == 2
    assert steps[0].status == "success"
    assert steps[1].status == "pending"
    assert steps[1].output_json == {}
    assert steps[2].status == "pending"


def test_reset_for_retry_keeps_skipped() -> None:
    steps = [_StubStep("skipped"), _StubStep("cancelled")]
    repo = _RepoForRetryTest(steps)
    count = repo.reset_for_retry(workflow_run_id="00000000-0000-0000-0000-000000000002", auto_commit=False)
    assert count == 1
    assert steps[0].status == "skipped"
    assert steps[1].status == "pending"
