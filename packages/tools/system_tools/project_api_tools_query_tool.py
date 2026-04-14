from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class ProjectApiToolItem:
    """项目接口中的单个“工具”定义。"""

    name: str
    method: str
    path: str
    tag: str
    summary: str


class ProjectApiToolsQueryTool:
    """通过 OpenAPI 查询当前项目可用接口工具列表。"""

    def __init__(self, *, timeout_seconds: float = 15.0) -> None:
        self.timeout_seconds = max(1.0, float(timeout_seconds))

    def run(
        self,
        *,
        base_url: str = "http://127.0.0.1:8080",
        project_path_prefix: str = "/v2/projects/{project_id}",
    ) -> dict[str, Any]:
        openapi_url = f"{str(base_url).rstrip('/')}/openapi.json"
        response = httpx.get(openapi_url, timeout=self.timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        paths = payload.get("paths")
        if not isinstance(paths, dict):
            raise RuntimeError("OpenAPI payload 缺少 paths")

        items: list[ProjectApiToolItem] = []
        for path, methods in paths.items():
            if not isinstance(path, str) or not path.startswith(project_path_prefix):
                continue
            if not isinstance(methods, dict):
                continue
            for method, operation in methods.items():
                if not isinstance(operation, dict):
                    continue
                op_name = str(operation.get("operationId") or "").strip()
                summary = str(operation.get("summary") or "").strip()
                tag = ""
                tags = operation.get("tags")
                if isinstance(tags, list) and tags:
                    tag = str(tags[0] or "").strip()
                name = op_name or f"{method.upper()} {path}"
                items.append(
                    ProjectApiToolItem(
                        name=name,
                        method=str(method).upper(),
                        path=path,
                        tag=tag,
                        summary=summary,
                    )
                )

        items.sort(key=lambda x: (x.path, x.method, x.name))
        return {
            "source": openapi_url,
            "count": len(items),
            "items": [
                {
                    "name": item.name,
                    "method": item.method,
                    "path": item.path,
                    "tag": item.tag,
                    "summary": item.summary,
                }
                for item in items
            ],
        }
