from __future__ import annotations

import logging

from packages.llm.text_generation.base import TextGenerationProvider
from packages.llm.text_generation.openai_compatible import OpenAICompatibleTextProvider
from packages.llm.text_generation.provider_registry import detect_provider
from packages.llm.text_generation.runtime_config import TextGenerationRuntimeConfig

logger = logging.getLogger("writeragent.llm")


def create_text_generation_provider(
    config: TextGenerationRuntimeConfig | None = None,
) -> TextGenerationProvider:
    cfg = config or TextGenerationRuntimeConfig.from_env()
    detected = detect_provider(base_url=cfg.base_url, model=cfg.model)
    profile_floor = float(detected.profile.default_timeout) if detected.profile else 0.0
    base_timeout = float(cfg.timeout_seconds)
    if cfg.timeout_use_provider_floor and profile_floor > 0:
        effective_timeout = max(base_timeout, profile_floor)
    else:
        effective_timeout = base_timeout
    effective_timeout = min(effective_timeout, 900.0)
    if effective_timeout != base_timeout:
        logger.info(
            "[LLM] 读超时 %.1fs → %.1fs（厂商建议下限=%.1fs，WRITER_LLM_TIMEOUT_USE_PROFILE_FLOOR=%s）",
            base_timeout,
            effective_timeout,
            profile_floor,
            str(cfg.timeout_use_provider_floor).lower(),
        )
    profile_max_out = (
        int(detected.profile.max_output_tokens)
        if detected.profile and detected.profile.max_output_tokens is not None
        else None
    )
    env_max_out = cfg.max_output_tokens
    max_output_cap = env_max_out if env_max_out is not None else profile_max_out
    if max_output_cap is not None:
        logger.info(
            "[LLM] max_output_tokens 将裁剪至 ≤%s（WRITER_LLM_MAX_OUTPUT_TOKENS=%s，profile=%s）",
            max_output_cap,
            env_max_out if env_max_out is not None else "（未设）",
            profile_max_out if profile_max_out is not None else "（无）",
        )
    return OpenAICompatibleTextProvider(
        api_key=cfg.api_key,
        model=cfg.model,
        base_url=cfg.base_url,
        timeout_seconds=effective_timeout,
        prompt_guard_enabled=cfg.prompt_guard_enabled,
        model_context_window_tokens=cfg.model_context_window_tokens,
        prompt_guard_output_reserve_tokens=cfg.prompt_guard_output_reserve_tokens,
        prompt_guard_overhead_tokens=cfg.prompt_guard_overhead_tokens,
        prompt_guard_max_attempts=cfg.prompt_guard_max_attempts,
        prompt_guard_llm_max_input_chars=cfg.prompt_guard_llm_max_input_chars,
        compat_mode=cfg.compat_mode,
        max_output_tokens_cap=max_output_cap,
    )
