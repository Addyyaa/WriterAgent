from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TextGenerationRequest:
    system_prompt: str
    user_prompt: str
    temperature: float = 0.7
    max_tokens: int | None = None
    # 单次 HTTP 读超时（秒）；未设则使用 Provider 构造时的 timeout（如 factory 合并厂商下限后值）
    timeout_seconds: float | None = None
    metadata_json: dict[str, Any] = field(default_factory=dict)
    input_payload: Any | None = None
    input_schema: dict[str, Any] | None = None
    input_schema_name: str | None = None
    input_schema_strict: bool = True
    response_schema: dict[str, Any] | None = None
    response_schema_name: str | None = None
    response_schema_strict: bool = True
    validation_retries: int = 1
    use_function_calling: bool = False
    function_name: str | None = None
    function_description: str | None = None


@dataclass(frozen=True)
class TextGenerationResult:
    text: str
    json_data: dict[str, Any]
    model: str
    provider: str
    is_mock: bool
    raw_response_json: dict[str, Any] = field(default_factory=dict)


class TextGenerationProvider(ABC):
    @abstractmethod
    def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        raise NotImplementedError
