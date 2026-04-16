from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from apps.orchestrator.worker import run_worker_loop, run_worker_once


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WriterAgent orchestrator worker")
    parser.add_argument("--once", action="store_true", help="只处理一轮任务")
    parser.add_argument("--log-file", default=None, help="日志文件路径（默认 data/worker.log）")
    parser.add_argument("--log-level", default=None, help="日志级别（默认 INFO）")
    return parser.parse_args()

def _setup_logging(*, log_file: str | None, log_level: str | None) -> None:
    level_name = str(log_level or os.getenv("WRITER_WORKER_LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    target_file = str(log_file or os.getenv("WRITER_WORKER_LOG_FILE") or "data/worker.log").strip()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if target_file:
        path = Path(target_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        handlers=handlers,
        force=True,
    )

    llm_log_path = Path(os.getenv("WRITER_LLM_LOG_FILE", "data/llm.log"))
    llm_log_path.parent.mkdir(parents=True, exist_ok=True)
    llm_handler = logging.FileHandler(llm_log_path, encoding="utf-8")
    llm_handler.setFormatter(fmt)
    llm_handler.setLevel(logging.DEBUG)
    llm_logger = logging.getLogger("writeragent.llm")
    llm_logger.addHandler(llm_handler)
    audit_logger = logging.getLogger("writeragent.llm_audit")
    if llm_handler not in audit_logger.handlers:
        audit_logger.addHandler(llm_handler)
    if audit_logger.getEffectiveLevel() > logging.DEBUG:
        audit_logger.setLevel(logging.DEBUG)


def main() -> None:
    args = _parse_args()
    _setup_logging(log_file=args.log_file, log_level=args.log_level)
    logging.getLogger("writeragent.worker").info("worker script started once=%s", bool(args.once))
    if args.once:
        processed = run_worker_once()
        logging.getLogger("writeragent.worker").info("worker script finished once processed=%s", int(processed))
        return
    run_worker_loop()


if __name__ == "__main__":
    main()
