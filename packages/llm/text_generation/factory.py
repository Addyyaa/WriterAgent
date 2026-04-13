from __future__ import annotations

from packages.llm.text_generation.base import TextGenerationProvider
from packages.llm.text_generation.mock_provider import MockTextGenerationProvider
from packages.llm.text_generation.openai_compatible import OpenAICompatibleTextProvider
from packages.llm.text_generation.runtime_config import TextGenerationRuntimeConfig


def create_text_generation_provider(
    config: TextGenerationRuntimeConfig | None = None,
) -> TextGenerationProvider:
    cfg = config or TextGenerationRuntimeConfig.from_env()
    if cfg.use_mock:
        return MockTextGenerationProvider(model=f"mock::{cfg.model}")
    return OpenAICompatibleTextProvider(
        api_key=cfg.api_key,
        model=cfg.model,
        base_url=cfg.base_url,
        timeout_seconds=cfg.timeout_seconds,
        bypass_to_mock=False,
        fallback_to_mock_on_error=cfg.fallback_to_mock_on_error,
        prompt_guard_enabled=cfg.prompt_guard_enabled,
        model_context_window_tokens=cfg.model_context_window_tokens,
        prompt_guard_output_reserve_tokens=cfg.prompt_guard_output_reserve_tokens,
        prompt_guard_overhead_tokens=cfg.prompt_guard_overhead_tokens,
        prompt_guard_max_attempts=cfg.prompt_guard_max_attempts,
        prompt_guard_llm_max_input_chars=cfg.prompt_guard_llm_max_input_chars,
    )
