from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    # packages/tools/system_tools/agent_tools_guide.py -> .../WriterAgent
    return Path(__file__).resolve().parents[3]


def default_agents_shared_dir() -> Path:
    """默认与 AgentRegistry 根目录 apps/agents 下的 _shared 一致。"""
    return _repo_root() / "apps" / "agents" / "_shared"


def load_runtime_local_tools_catalog(*, shared_dir: Path | None = None) -> list[dict[str, Any]]:
    path = (shared_dir or default_agents_shared_dir()) / "local_data_tools_catalog.json"
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


def load_agent_local_database_tools_guide(*, shared_dir: Path | None = None) -> str:
    path = (shared_dir or default_agents_shared_dir()) / "local_data_tools.md"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


# 向后兼容：静态导入场景下与磁盘配置同步（优先读 apps/agents/_shared）。
RUNTIME_LOCAL_TOOLS_CATALOG: list[dict[str, Any]] = load_runtime_local_tools_catalog()
AGENT_LOCAL_DATABASE_TOOLS_GUIDE: str = load_agent_local_database_tools_guide()
