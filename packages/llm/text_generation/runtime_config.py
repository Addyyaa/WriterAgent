from __future__ import annotations

import os
from dataclasses import dataclass

from packages.core.config import env_bool, env_float, env_float_or_none, env_int, env_str


@dataclass(frozen=True)
class TextGenerationRuntimeConfig:
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "qwen-plus"
    timeout_seconds: float = 60.0
    prompt_guard_enabled: bool = True
    model_context_window_tokens: int = 128000
    prompt_guard_output_reserve_tokens: int = 4096
    prompt_guard_overhead_tokens: int = 256
    prompt_guard_max_attempts: int = 2
    prompt_guard_llm_max_input_chars: int = 32000
    compat_mode: str = "auto"
    # 为 True 时，实际读超时取 max(WRITER_LLM_TIMEOUT, 厂商 registry 中的 default_timeout)
    timeout_use_provider_floor: bool = True
    # 显式设置时覆盖厂商默认的 max_output_tokens 上限；未设置则采用 provider_registry 中的 max_output_tokens。
    max_output_tokens: int | None = None
    # 修订工作流单次 LLM 读超时（秒，1~900）；未设则仅用 WRITER_LLM_TIMEOUT + 厂商下限
    revision_llm_timeout_seconds: float | None = None

    @classmethod
    def from_env(cls) -> "TextGenerationRuntimeConfig":
        return cls(
            base_url=env_str("WRITER_LLM_BASE_URL", "https://api.openai.com/v1"),
            api_key=env_str("WRITER_LLM_API_KEY", ""),
            model=env_str("WRITER_LLM_MODEL", "qwen-plus"),
            # 长章节 + function_calling JSON 在部分厂商上可能超过数分钟，上限放宽到 15 分钟
            timeout_seconds=env_float("WRITER_LLM_TIMEOUT", 60.0, minimum=1.0, maximum=900.0),
            prompt_guard_enabled=env_bool("WRITER_LLM_PROMPT_GUARD_ENABLED", True),
            model_context_window_tokens=env_int("WRITER_LLM_CONTEXT_WINDOW_TOKENS", 128000),
            prompt_guard_output_reserve_tokens=env_int(
                "WRITER_LLM_PROMPT_GUARD_OUTPUT_RESERVE_TOKENS",
                4096,
            ),
            prompt_guard_overhead_tokens=env_int(
                "WRITER_LLM_PROMPT_GUARD_OVERHEAD_TOKENS",
                256,
            ),
            prompt_guard_max_attempts=env_int("WRITER_LLM_PROMPT_GUARD_MAX_ATTEMPTS", 2),
            prompt_guard_llm_max_input_chars=env_int(
                "WRITER_LLM_PROMPT_GUARD_LLM_MAX_INPUT_CHARS",
                32000,
            ),
            compat_mode=env_str("WRITER_LLM_COMPAT_MODE", "auto"),
            timeout_use_provider_floor=env_bool("WRITER_LLM_TIMEOUT_USE_PROFILE_FLOOR", True),
            max_output_tokens=_env_optional_positive_int("WRITER_LLM_MAX_OUTPUT_TOKENS"),
            revision_llm_timeout_seconds=env_float_or_none(
                "WRITER_REVISION_LLM_TIMEOUT",
                default=None,
                minimum=1.0,
                maximum=900.0,
            ),
        )


def _env_optional_positive_int(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return None
    try:
        return max(1, int(str(raw).strip()))
    except ValueError:
        return None
