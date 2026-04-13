from __future__ import annotations

import unittest

from packages.workflows.orchestration.run_events import (
    build_run_events,
    events_since_cursor,
    last_seq,
    terminal_status_reached,
)


class TestRunEvents(unittest.TestCase):
    def test_build_run_events_contains_core_events(self) -> None:
        detail = {
            "id": "run-1",
            "trace_id": "trace-1",
            "status": "success",
            "created_at": "2026-04-13T10:00:00Z",
            "started_at": "2026-04-13T10:00:05Z",
            "updated_at": "2026-04-13T10:00:20Z",
            "finished_at": "2026-04-13T10:00:30Z",
            "steps": [
                {
                    "id": 1,
                    "step_key": "outline",
                    "step_type": "outline_generation",
                    "workflow_type": "outline_generation",
                    "status": "success",
                    "attempt_count": 1,
                    "role_id": "planner",
                    "started_at": "2026-04-13T10:00:06Z",
                    "finished_at": "2026-04-13T10:00:10Z",
                    "error_code": None,
                    "error_message": None,
                },
                {
                    "id": 2,
                    "step_key": "review",
                    "step_type": "consistency_review",
                    "workflow_type": "consistency_review",
                    "status": "failed",
                    "attempt_count": 1,
                    "role_id": "reviewer",
                    "started_at": "2026-04-13T10:00:11Z",
                    "finished_at": "2026-04-13T10:00:20Z",
                    "error_code": "CONSISTENCY_FAILED",
                    "error_message": "conflict",
                },
            ],
            "candidates": [
                {
                    "id": "cand-1",
                    "workflow_step_id": 2,
                    "chapter_no": 3,
                    "title": "候选",
                    "status": "approved",
                    "approved_chapter_id": "ch-1",
                    "approved_version_id": 7,
                    "created_at": "2026-04-13T10:00:12Z",
                    "approved_at": "2026-04-13T10:00:25Z",
                    "rejected_at": None,
                }
            ],
        }

        events = build_run_events(detail)
        self.assertGreaterEqual(len(events), 8)
        self.assertEqual(events[0]["seq"], 1)
        self.assertEqual(events[-1]["seq"], len(events))
        self.assertEqual(events[-1]["event_type"], "run_completed")
        self.assertTrue(any(item["event_type"] == "step_started" for item in events))
        self.assertTrue(any(item["event_type"] == "step_succeeded" for item in events))
        self.assertTrue(any(item["event_type"] == "step_failed" for item in events))
        self.assertTrue(any(item["event_type"] == "candidate_waiting_review" for item in events))
        self.assertTrue(any(item["event_type"] == "candidate_approved" for item in events))

    def test_cursor_filter(self) -> None:
        events = [
            {"seq": 1, "event_type": "a"},
            {"seq": 2, "event_type": "b"},
            {"seq": 3, "event_type": "c"},
        ]
        filtered = events_since_cursor(events, 1)
        self.assertEqual([item["seq"] for item in filtered], [2, 3])

    def test_terminal_helpers(self) -> None:
        success_detail = {"status": "success"}
        running_detail = {"status": "running"}
        events = [{"seq": 3}, {"seq": 8}]

        self.assertTrue(terminal_status_reached(success_detail))
        self.assertFalse(terminal_status_reached(running_detail))
        self.assertEqual(last_seq(events), 8)
        self.assertEqual(last_seq([]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
