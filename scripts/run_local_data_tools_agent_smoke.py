#!/usr/bin/env python3
"""本地数据工具 + 各 agent 系统提示的冒烟：建议优先用 pytest 集测。

用法：
  ./venv/bin/python -m pytest tests/integration/test_local_data_tools_agent_llm.py -v

本脚本将上述 pytest 结果摘要追加到 data/worker.log（需已安装 pytest）。
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    log_path = repo / "data" / "worker.log"
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(repo / "tests" / "integration" / "test_local_data_tools_agent_llm.py"),
        "-v",
        "--tb=no",
    ]
    proc = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True)
    block = (
        f"=== LOCAL DATA TOOLS AGENT SMOKE {datetime.now().isoformat(timespec='seconds')} ===\n"
        f"exit_code={proc.returncode}\n"
        f"--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}\n"
        f"=== END LOCAL DATA TOOLS AGENT SMOKE ===\n"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(block)
    print(block)
    return int(proc.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
