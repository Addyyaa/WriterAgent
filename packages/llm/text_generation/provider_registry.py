"""
多厂商 LLM Provider 兼容性注册表。

每个厂商注册自身的 URL 模式、模型前缀、能力矩阵，在运行时
根据用户配置的 base_url + model 自动匹配最佳兼容参数。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

logger = logging.getLogger("writeragent.llm")


@dataclass(frozen=True)
class ProviderProfile:
    """单个厂商的兼容性描述。"""

    name: str
    display_name: str
    url_patterns: tuple[str, ...]
    model_prefixes: tuple[str, ...] = ()
    supports_json_schema: bool = False
    supports_function_calling: bool = False
    supports_json_object: bool = True
    # OpenAI 风格 {"type":"function","function":{"name":...}} 会强制走工具调用；
    # 部分兼容网关（如 DashScope）不接受，仅支持 auto/none。
    supports_forced_function_tool_choice: bool = True
    default_timeout: float = 60.0
    default_context_window: int = 128000
    notes: str = ""


_REGISTRY: list[ProviderProfile] = [
    ProviderProfile(
        name="openai",
        display_name="OpenAI",
        url_patterns=("api.openai.com",),
        model_prefixes=("gpt-", "o1", "o3", "o4"),
        supports_json_schema=True,
        supports_function_calling=True,
        default_timeout=60.0,
        default_context_window=128000,
    ),
    ProviderProfile(
        name="openrouter",
        display_name="OpenRouter",
        url_patterns=("openrouter.ai",),
        model_prefixes=(),
        supports_json_schema=True,
        supports_function_calling=True,
        default_timeout=90.0,
        default_context_window=128000,
        notes="聚合多厂商模型，兼容性取决于底层模型",
    ),
    ProviderProfile(
        name="dashscope",
        display_name="阿里云 DashScope（通义千问）",
        url_patterns=("dashscope.aliyuncs.com",),
        model_prefixes=("qwen",),
        supports_json_schema=False,
        supports_function_calling=True,
        supports_json_object=True,
        supports_forced_function_tool_choice=False,
        default_timeout=120.0,
        default_context_window=262144,
        notes="通义千问系列，function_calling 可用但 json_schema 不支持",
    ),
    ProviderProfile(
        name="zhipu",
        display_name="智谱 AI（GLM）",
        url_patterns=("open.bigmodel.cn",),
        model_prefixes=("glm-", "chatglm"),
        supports_json_schema=False,
        supports_function_calling=True,
        supports_json_object=True,
        default_timeout=90.0,
        default_context_window=128000,
    ),
    ProviderProfile(
        name="moonshot",
        display_name="月之暗面（Kimi）",
        url_patterns=("api.moonshot.cn",),
        model_prefixes=("moonshot-",),
        supports_json_schema=False,
        supports_function_calling=True,
        supports_json_object=True,
        default_timeout=90.0,
        default_context_window=128000,
    ),
    ProviderProfile(
        name="deepseek",
        display_name="DeepSeek",
        url_patterns=("api.deepseek.com",),
        model_prefixes=("deepseek-",),
        supports_json_schema=False,
        supports_function_calling=True,
        supports_json_object=True,
        default_timeout=120.0,
        default_context_window=65536,
    ),
    ProviderProfile(
        name="baichuan",
        display_name="百川智能",
        url_patterns=("api.baichuan-ai.com",),
        model_prefixes=("baichuan",),
        supports_json_schema=False,
        supports_function_calling=False,
        supports_json_object=True,
        default_timeout=90.0,
        default_context_window=32768,
    ),
    ProviderProfile(
        name="minimax",
        display_name="MiniMax",
        url_patterns=("api.minimax.chat",),
        model_prefixes=("abab",),
        supports_json_schema=False,
        supports_function_calling=True,
        supports_json_object=True,
        default_timeout=90.0,
        default_context_window=245760,
    ),
    ProviderProfile(
        name="lingyiwanwu",
        display_name="零一万物（Yi）",
        url_patterns=("api.lingyiwanwu.com",),
        model_prefixes=("yi-",),
        supports_json_schema=False,
        supports_function_calling=True,
        supports_json_object=True,
        default_timeout=90.0,
        default_context_window=200000,
    ),
    ProviderProfile(
        name="xfyun",
        display_name="讯飞星火",
        url_patterns=("spark-api-open.xf-yun.com",),
        model_prefixes=("spark",),
        supports_json_schema=False,
        supports_function_calling=False,
        supports_json_object=True,
        default_timeout=90.0,
        default_context_window=128000,
    ),
    ProviderProfile(
        name="siliconflow",
        display_name="SiliconFlow",
        url_patterns=("api.siliconflow.cn",),
        model_prefixes=(),
        supports_json_schema=False,
        supports_function_calling=True,
        supports_json_object=True,
        default_timeout=90.0,
        default_context_window=128000,
        notes="聚合多模型，兼容性取决于底层模型",
    ),
    ProviderProfile(
        name="anthropic_compatible",
        display_name="Anthropic (OpenAI 兼容)",
        url_patterns=("api.anthropic.com",),
        model_prefixes=("claude-",),
        supports_json_schema=False,
        supports_function_calling=True,
        supports_json_object=True,
        default_timeout=120.0,
        default_context_window=200000,
    ),
]


@dataclass
class MatchResult:
    """自动匹配结果。"""

    profile: ProviderProfile | None
    matched_by: str
    confidence: str
    compat_mode: str


def detect_provider(*, base_url: str, model: str) -> MatchResult:
    """根据 base_url 和 model 名称自动匹配厂商。"""
    host = ""
    try:
        host = urlparse(base_url).hostname or ""
    except Exception:
        pass

    model_lower = model.lower()

    for p in _REGISTRY:
        url_match = any(pat in host for pat in p.url_patterns)
        model_match = any(model_lower.startswith(pf) for pf in p.model_prefixes)

        if url_match and model_match:
            return MatchResult(
                profile=p,
                matched_by="url+model",
                confidence="high",
                compat_mode=_derive_compat_mode(p),
            )
        if url_match:
            return MatchResult(
                profile=p,
                matched_by="url",
                confidence="high",
                compat_mode=_derive_compat_mode(p),
            )

    for p in _REGISTRY:
        if p.model_prefixes and any(model_lower.startswith(pf) for pf in p.model_prefixes):
            return MatchResult(
                profile=p,
                matched_by="model",
                confidence="medium",
                compat_mode=_derive_compat_mode(p),
            )

    return MatchResult(
        profile=None,
        matched_by="none",
        confidence="low",
        compat_mode="full",
    )


def _derive_compat_mode(p: ProviderProfile) -> str:
    if p.supports_json_schema and p.supports_function_calling:
        return "full"
    return "basic"


def log_provider_detection(*, base_url: str, model: str, user_override: str) -> tuple[str, MatchResult]:
    """
    在启动时执行检测并输出日志，返回最终 compat_mode 与匹配结果。

    如果用户通过 WRITER_LLM_COMPAT_MODE 显式指定了 full/basic，
    则尊重用户选择并在日志中说明。
    """
    result = detect_provider(base_url=base_url, model=model)

    if user_override in ("full", "basic"):
        logger.info(
            "[LLM Provider] 用户显式指定 compat_mode=%s (检测到厂商=%s matched_by=%s)",
            user_override,
            result.profile.display_name if result.profile else "未知",
            result.matched_by,
        )
        return user_override, result

    if result.profile:
        logger.info(
            "[LLM Provider] ✓ 自动识别厂商: %s | matched_by=%s confidence=%s | "
            "compat_mode=%s | json_schema=%s function_calling=%s | 默认超时=%ss 上下文窗口=%d",
            result.profile.display_name,
            result.matched_by,
            result.confidence,
            result.compat_mode,
            result.profile.supports_json_schema,
            result.profile.supports_function_calling,
            result.profile.default_timeout,
            result.profile.default_context_window,
        )
        if result.profile.notes:
            logger.info("[LLM Provider] 备注: %s", result.profile.notes)
    else:
        logger.warning(
            "[LLM Provider] ⚠ 未识别厂商 | base_url=%s model=%s | "
            "将使用 compat_mode=full（完整功能模式），如遇问题请设置 WRITER_LLM_COMPAT_MODE=basic",
            base_url, model,
        )

    return result.compat_mode, result


def get_registry() -> list[ProviderProfile]:
    return list(_REGISTRY)


def get_provider_profile(name: str) -> ProviderProfile | None:
    for p in _REGISTRY:
        if p.name == name:
            return p
    return None
