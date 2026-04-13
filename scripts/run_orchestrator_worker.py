from __future__ import annotations

import argparse

from apps.orchestrator.worker import run_worker_loop, run_worker_once


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WriterAgent orchestrator worker")
    parser.add_argument("--once", action="store_true", help="只处理一轮任务")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.once:
        processed = run_worker_once()
        print({"processed": processed})
        return
    run_worker_loop()


if __name__ == "__main__":
    main()
