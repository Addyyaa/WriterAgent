from __future__ import annotations

from typing import Any

from packages.evaluation.consistency.metrics import status_to_score


def build_writing_score_breakdown(detail: dict[str, Any]) -> dict[str, float]:
    steps = list(detail.get("steps") or [])
    by_key = {str(item.get("step_key")): item for item in steps}

    def _success(key: str) -> bool:
        return str((by_key.get(key) or {}).get("status") or "") == "success"

    structure_integrity = 1.0 if _success("outline_generation") else 0.0
    retrieval_hit_score = 1.0 if _success("retrieval_context") else 0.0

    consistency_step = by_key.get("consistency_review") or {}
    consistency_output = dict(consistency_step.get("output_json") or {})
    consistency_score = consistency_output.get("score")
    if consistency_score is None:
        consistency_status = consistency_output.get("status")
        if consistency_status is None:
            consistency_status = "passed" if _success("consistency_review") else "failed"
        consistency_value = status_to_score(str(consistency_status))
    else:
        try:
            consistency_value = max(0.0, min(float(consistency_score), 1.0))
        except (TypeError, ValueError):
            consistency_value = 0.0

    revision_output = dict((by_key.get("writer_revision") or {}).get("output_json") or {})
    revised = bool(revision_output.get("revised"))
    revision_gain = 1.0 if revised else (1.0 if _success("writer_revision") else 0.0)

    return {
        "structure_integrity": structure_integrity,
        "retrieval_hit_score": retrieval_hit_score,
        "consistency_score": consistency_value,
        "revision_gain": revision_gain,
    }
