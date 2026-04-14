"""LLM 结构化输出校验相关异常。"""

from __future__ import annotations

from typing import Any


class ResponseSchemaValidationError(RuntimeError):
    """
    响应 JSON 已通过解析，但未通过 response_schema 校验。

    携带最后一次解析得到的 json_data，供上层在「长文 minLength」等场景下回收短稿并走扩写/降级。
    """

    def __init__(
        self,
        message: str,
        *,
        errors: list[str],
        json_data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.errors = list(errors or [])
        self.json_data = dict(json_data or {})
