from __future__ import annotations

import os
import time
import uuid

import pytest
import requests

BASE_URL = os.getenv("WRITER_E2E_BASE_URL", "").strip()
USERNAME = os.getenv("WRITER_E2E_USERNAME", "").strip()
PASSWORD = os.getenv("WRITER_E2E_PASSWORD", "").strip()


@pytest.mark.e2e
def test_writing_run_review_flow() -> None:
    if not BASE_URL or not USERNAME or not PASSWORD:
        pytest.skip("missing WRITER_E2E_BASE_URL / WRITER_E2E_USERNAME / WRITER_E2E_PASSWORD")

    session = requests.Session()
    login = session.post(
        f"{BASE_URL}/v2/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
        timeout=30,
    )
    assert login.status_code == 200, login.text
    token = login.json().get("access_token")
    assert token

    headers = {"Authorization": f"Bearer {token}"}
    project = session.post(
        f"{BASE_URL}/v2/projects",
        json={"title": f"e2e-{uuid.uuid4()}", "genre": "test", "premise": "e2e flow"},
        headers=headers,
        timeout=30,
    )
    assert project.status_code == 200, project.text
    project_id = project.json()["id"]

    run_resp = session.post(
        f"{BASE_URL}/v2/projects/{project_id}/writing/runs",
        json={
            "workflow_type": "writing_full",
            "writing_goal": "e2e run lifecycle",
            "target_words": 800,
        },
        headers=headers,
        timeout=30,
    )
    assert run_resp.status_code == 200, run_resp.text
    run_id = run_resp.json()["run_id"]

    final_status = None
    for _ in range(60):
        detail = session.get(f"{BASE_URL}/v2/writing/runs/{run_id}", headers=headers, timeout=30)
        assert detail.status_code == 200, detail.text
        status = detail.json().get("status")
        if status in {"success", "failed", "cancelled", "waiting_review"}:
            final_status = status
            break
        time.sleep(1)

    assert final_status in {"success", "failed", "cancelled", "waiting_review"}
