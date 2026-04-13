from __future__ import annotations

import argparse
import json

from packages.evaluation.service import OnlineEvaluationService
from packages.retrieval.evaluators.online_eval import OnlineEvalEvent, OnlineEvaluator
from packages.retrieval.evaluators.online_eval_service import OnlineEvalService
from packages.storage.postgres.repositories.evaluation_repository import EvaluationRepository
from packages.storage.postgres.repositories.retrieval_eval_repository import RetrievalEvalRepository
from packages.storage.postgres.session import create_session_factory


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize online eval stats")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--window-limit", type=int, default=1000)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    session_factory = create_session_factory()
    db = session_factory()
    try:
        repo = RetrievalEvalRepository(db)
        service = OnlineEvalService(repo)
        daily = service.get_daily_stats(project_id=args.project_id)
        unified = OnlineEvaluationService(repo=EvaluationRepository(db))
        unified_daily = unified.list_daily(project_id=args.project_id, evaluation_type=None, days=90)

        # 额外跑一层内存聚合，验证 online_eval 基础实现。
        evaluator = OnlineEvaluator()
        for item in daily:
            for _ in range(int(item.impressions)):
                evaluator.record(
                    OnlineEvalEvent(
                        user_id="daily",
                        query=item.stat_date,
                        variant=item.variant,
                        clicked=False,
                    )
                )
            for _ in range(int(item.clicks)):
                evaluator.record(
                    OnlineEvalEvent(
                        user_id="daily",
                        query=item.stat_date,
                        variant=item.variant,
                        clicked=True,
                    )
                )

        print(
            json.dumps(
                {
                    "daily": [item.__dict__ for item in daily[: max(1, int(args.window_limit))]],
                    "unified_daily": [item.__dict__ for item in unified_daily[: max(1, int(args.window_limit))]],
                    "in_memory_report": [item.__dict__ for item in evaluator.report()],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
