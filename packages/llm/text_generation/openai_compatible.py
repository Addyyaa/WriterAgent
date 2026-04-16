from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import replace
from typing import Any

import httpx

from packages.core.utils import (
    compress_text_to_budget,
    ensure_non_empty_string,
    estimate_token_count,
)
from packages.core.utils.chapter_metrics import count_fiction_word_units
from packages.llm.text_generation.base import (
    TextGenerationProvider,
    TextGenerationRequest,
    TextGenerationResult,
)
from packages.llm.text_generation.provider_registry import MatchResult
from packages.llm.text_generation.schema_errors import ResponseSchemaValidationError
from packages.llm.prompt_audit import record_llm_prompt_audit

logger = logging.getLogger("writeragent.llm")


def _log_llm_json_response_lens(
    *,
    meta_tag: str,
    primary_text: str,
    json_data: Any,
    target_words: int | None = None,
) -> None:
    """打印解析后 JSON 各块长度（不写正文），用于对照有效字数与是否截断/字段错位。"""
    primary_text_len = len(primary_text or "")
    primary_text_non_ws = count_fiction_word_units(primary_text or "")
    if not isinstance(json_data, dict):
        logger.info(
            "[LLM] response_lens | meta=%s primary_text_len=%d json_data_type=%s",
            meta_tag,
            primary_text_len,
            type(json_data).__name__,
        )
        logger.info(
            "[LLM] response_word_stats | meta=%s primary_text_non_ws=%d json_data_type=%s",
            meta_tag,
            primary_text_non_ws,
            type(json_data).__name__,
        )
        return
    try:
        json_dump_len = len(json.dumps(json_data, ensure_ascii=False))
    except Exception:
        json_dump_len = -1
    ch = json_data.get("chapter")
    ch_strlen: int | None = None
    ch_eff: int | None = None
    if isinstance(ch, dict):
        c = str(ch.get("content") or "")
        ch_strlen = len(c)
        ch_eff = count_fiction_word_units(c)
    top_raw = json_data.get("content")
    top_len: int | None = None
    top_eff: int | None = None
    if top_raw is not None:
        t = str(top_raw)
        top_len = len(t)
        top_eff = count_fiction_word_units(t)
    segs = json_data.get("segments")
    seg_n = 0
    seg_join_eff = 0
    if isinstance(segs, list):
        parts: list[str] = []
        for item in segs:
            if isinstance(item, dict):
                seg_n += 1
                parts.append(str(item.get("content") or ""))
        seg_join_eff = count_fiction_word_units("\n".join(parts))
    logger.info(
        "[LLM] response_lens | meta=%s primary_text_len=%d json_dump_len=%s "
        "chapter.content_strlen=%s chapter.content_non_ws=%s "
        "top_level.content_strlen=%s top_level.content_non_ws=%s "
        "segments=%d segments_join_non_ws=%d",
        meta_tag,
        primary_text_len,
        json_dump_len,
        ch_strlen,
        ch_eff,
        top_len,
        top_eff,
        seg_n,
        seg_join_eff,
    )
    candidates: list[tuple[str, int]] = []
    if ch_eff is not None:
        candidates.append(("chapter.content", int(ch_eff)))
    if top_eff is not None:
        candidates.append(("top_level.content", int(top_eff)))
    if seg_n > 0:
        candidates.append(("segments_join", int(seg_join_eff)))
    if not candidates:
        candidates.append(("primary_text", int(primary_text_non_ws)))
    best_source, best_non_ws = max(candidates, key=lambda x: x[1])

    low = high = gap_to_min = gap_to_max = None
    if isinstance(target_words, int) and target_words > 0:
        low = int(target_words * 0.9)
        high = int(target_words * 1.1)
        gap_to_min = int(best_non_ws - low)
        gap_to_max = int(high - best_non_ws)

    logger.info(
        "[LLM] response_word_stats | meta=%s primary_text_non_ws=%d "
        "chapter.content_non_ws=%s top_level.content_non_ws=%s segments_join_non_ws=%d "
        "selected_metric=%s selected_non_ws=%d target_words=%s allowed=[%s,%s] "
        "gap_to_min=%s gap_to_max=%s",
        meta_tag,
        primary_text_non_ws,
        ch_eff,
        top_eff,
        seg_join_eff,
        best_source,
        best_non_ws,
        target_words,
        low,
        high,
        gap_to_min,
        gap_to_max,
    )


def _repair_truncated_json(text: str) -> dict[str, Any] | None:
    """尝试修复被 max_tokens 截断的 JSON（补全缺失的括号）。"""
    text = text.rstrip()
    if not text.startswith("{"):
        return None
    close_suffixes = [
        '"}', '"}]', '"}]}', '"}}',
        "}", "]}", "]}}", '""}'
    ]
    for suffix in close_suffixes:
        for s in [suffix, "..." + suffix, '""' + suffix]:
            candidate = text + s
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                continue
    depth_brace = 0
    depth_bracket = 0
    in_string = False
    escape_next = False
    for ch in text:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth_brace += 1
        elif ch == "}":
            depth_brace -= 1
        elif ch == "[":
            depth_bracket += 1
        elif ch == "]":
            depth_bracket -= 1
    if in_string:
        text += '"'
    text += "]" * max(0, depth_bracket)
    text += "}" * max(0, depth_brace)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return None


class LLMApiError(RuntimeError):
    """带 HTTP 状态码的 LLM API 错误，便于上层区分可恢复/不可恢复。"""

    NON_RETRYABLE_CODES = {401, 403, 429}

    def __init__(self, message: str, *, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code

    @property
    def is_rate_limited(self) -> bool:
        return self.status_code == 429

    @property
    def is_auth_error(self) -> bool:
        return self.status_code in {401, 403}

    @property
    def should_not_fallback_to_mock(self) -> bool:
        return self.status_code in self.NON_RETRYABLE_CODES


class OpenAICompatibleTextProvider(TextGenerationProvider):
    """
    OpenAI 兼容文本生成 Provider。

    说明：
    - 真实请求构建与响应解析逻辑已实现，可随时切换启用。
    - 新增整 Prompt token guard：检测超窗时，触发 LLM 二次压缩重试。
    """

    _CONTEXT_ERROR_HINTS = (
        "maximum context length",
        "context length",
        "too many tokens",
        "prompt is too long",
        "token limit",
    )

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 30.0,
        prompt_guard_enabled: bool = True,
        model_context_window_tokens: int = 128000,
        prompt_guard_output_reserve_tokens: int = 4096,
        prompt_guard_overhead_tokens: int = 256,
        prompt_guard_max_attempts: int = 2,
        prompt_guard_llm_max_input_chars: int = 12000,
        compat_mode: str = "auto",
        max_output_tokens_cap: int | None = None,
    ) -> None:
        self.api_key = ensure_non_empty_string(api_key, field_name="api_key")
        self.model = ensure_non_empty_string(model, field_name="model")
        self.base_url = ensure_non_empty_string(base_url, field_name="base_url").rstrip("/")
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.max_output_tokens_cap = (
            max(1, int(max_output_tokens_cap)) if max_output_tokens_cap is not None else None
        )

        self.prompt_guard_enabled = bool(prompt_guard_enabled)
        self.model_context_window_tokens = max(2048, int(model_context_window_tokens))
        self.prompt_guard_output_reserve_tokens = max(128, int(prompt_guard_output_reserve_tokens))
        self.prompt_guard_overhead_tokens = max(64, int(prompt_guard_overhead_tokens))
        self.prompt_guard_max_attempts = max(1, int(prompt_guard_max_attempts))
        self.prompt_guard_llm_max_input_chars = max(500, int(prompt_guard_llm_max_input_chars))
        self.compat_mode, self._provider_match = self._resolve_compat_mode(
            compat_mode, self.base_url, self.model
        )
        logger.info(
            "[LLM] provider init | pid=%s model=%s base_url=%s compat_mode=%s timeout=%.1fs "
            "| 尚无步骤上下文；具体 agent/步骤见同文件后续「generate start」的 meta= 与 llm_task_id",
            os.getpid(),
            self.model,
            self.base_url,
            self.compat_mode,
            self.timeout_seconds,
        )

    @staticmethod
    def _resolve_compat_mode(mode: str, base_url: str, model: str = "") -> tuple[str, MatchResult]:
        """
        通过 provider_registry 自动匹配厂商并确定兼容模式。
        - "full": 完全支持 json_schema + function_calling
        - "basic": 仅使用 json_object，schema 通过 prompt 传达
        - "auto": 根据 base_url + model 自动判断
        """
        from packages.llm.text_generation.provider_registry import log_provider_detection

        compat, match = log_provider_detection(
            base_url=base_url,
            model=model,
            user_override=str(mode or "auto").strip().lower(),
        )
        return compat, match

    def _forced_function_tool_choice_supported(self) -> bool:
        """是否可使用 OpenAI 风格强制指定函数的 tool_choice（部分兼容网关不支持）。"""
        profile = self._provider_match.profile
        if profile is None:
            return True
        return bool(profile.supports_forced_function_tool_choice)

    def _read_timeout_for(self, request: TextGenerationRequest) -> float:
        """单次请求的 HTTP 读超时，与 factory 侧上限 900s 对齐。"""
        if request.timeout_seconds is not None:
            return min(max(float(request.timeout_seconds), 1.0), 900.0)
        return float(self.timeout_seconds)

    def _record_llm_prompt_audit(
        self,
        *,
        llm_task_id: str,
        request: TextGenerationRequest,
        prompt_guard_applied: bool,
    ) -> None:
        record_llm_prompt_audit(
            llm_task_id=llm_task_id,
            system_prompt=str(request.system_prompt or ""),
            user_prompt=str(request.user_prompt or ""),
            model=self.model,
            provider_label="OpenAICompatibleTextProvider",
            metadata=dict(request.metadata_json or {}),
            prompt_guard_applied=prompt_guard_applied,
        )

    def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        llm_task_id = str(uuid.uuid4())
        request = replace(
            request,
            metadata_json={**dict(request.metadata_json or {}), "llm_task_id": llm_task_id},
        )
        effective_request = request
        input_validation = self._validate_request_input(request)
        prompt_guard = {"applied": False, "attempts": 0, "reason": "disabled_or_not_needed"}

        meta_tag = request.metadata_json.get("role_id", request.metadata_json.get("step_key", "unknown"))
        read_to = self._read_timeout_for(request)
        if request.timeout_seconds is not None and read_to != float(self.timeout_seconds):
            logger.info(
                "[LLM] generate start | llm_task_id=%s model=%s meta=%s prompt_len=%d max_tokens=%s read_timeout=%.1fs（按请求覆盖）",
                llm_task_id,
                self.model,
                meta_tag,
                len(request.user_prompt or ""),
                request.max_tokens or "None",
                read_to,
            )
        else:
            logger.info(
                "[LLM] generate start | llm_task_id=%s model=%s meta=%s prompt_len=%d max_tokens=%s",
                llm_task_id,
                self.model,
                meta_tag,
                len(request.user_prompt or ""),
                request.max_tokens or "None",
            )

        if self._should_apply_prompt_guard(request):
            effective_request, prompt_guard = self._apply_prompt_guard(
                request=request,
                force=False,
            )

        self._record_llm_prompt_audit(
            llm_task_id=llm_task_id,
            request=effective_request,
            prompt_guard_applied=bool(prompt_guard.get("applied")),
        )

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        logger.info("[LLM] sending to %s | model=%s meta=%s", url, self.model, meta_tag)
        try:
            parsed, runtime_meta = self._send_with_schema_repair(
                request=effective_request,
                url=url,
                headers=headers,
            )
            self._log_completion_usage(body=parsed.raw_response_json, meta_tag=meta_tag)
            logger.info(
                "[LLM] success | model=%s provider=%s meta=%s text_len=%d",
                parsed.model, parsed.provider, meta_tag, len(parsed.text or ""),
            )
            _log_llm_json_response_lens(
                meta_tag=meta_tag,
                primary_text=parsed.text or "",
                json_data=parsed.json_data,
                target_words=self._coerce_target_words(request.metadata_json),
            )
            with_guard = self._with_prompt_guard(
                parsed,
                prompt_guard={
                    **prompt_guard,
                    **runtime_meta,
                },
            )
            return self._with_input_validation(with_guard, input_validation=input_validation)
        except Exception as exc:
            logger.warning("[LLM] API error | meta=%s error=%s", meta_tag, str(exc)[:200])
            if self._should_apply_prompt_guard(effective_request) and self._is_context_length_error(exc):
                retry_request, retry_guard = self._apply_prompt_guard(
                    request=effective_request,
                    force=True,
                )
                if retry_request.user_prompt != effective_request.user_prompt:
                    retry_task_id = str(uuid.uuid4())
                    retry_request = replace(
                        retry_request,
                        metadata_json={
                            **dict(retry_request.metadata_json or {}),
                            "llm_task_id": retry_task_id,
                            "llm_task_id_prior": llm_task_id,
                        },
                    )
                    logger.info(
                        "[LLM] retrying with compressed prompt | llm_task_id=%s prior=%s meta=%s",
                        retry_task_id,
                        llm_task_id,
                        meta_tag,
                    )
                    self._record_llm_prompt_audit(
                        llm_task_id=retry_task_id,
                        request=retry_request,
                        prompt_guard_applied=True,
                    )
                    parsed, runtime_meta = self._send_with_schema_repair(
                        request=retry_request,
                        url=url,
                        headers=headers,
                    )
                    self._log_completion_usage(body=parsed.raw_response_json, meta_tag=meta_tag)
                    logger.info(
                        "[LLM] success | model=%s provider=%s meta=%s text_len=%d",
                        parsed.model, parsed.provider, meta_tag, len(parsed.text or ""),
                    )
                    _log_llm_json_response_lens(
                        meta_tag=meta_tag,
                        primary_text=parsed.text or "",
                        json_data=parsed.json_data,
                        target_words=self._coerce_target_words(request.metadata_json),
                    )
                    merged_guard = {
                        **prompt_guard,
                        **retry_guard,
                        **runtime_meta,
                        "second_retry_applied": True,
                    }
                    with_guard = self._with_prompt_guard(parsed, prompt_guard=merged_guard)
                    return self._with_input_validation(with_guard, input_validation=input_validation)
            raise

    def build_chat_payload(self, request: TextGenerationRequest) -> dict[str, Any]:
        system_prompt = ensure_non_empty_string(
            request.system_prompt,
            field_name="system_prompt",
        )
        user_prompt = ensure_non_empty_string(
            request.user_prompt,
            field_name="user_prompt",
        )

        is_basic = self.compat_mode == "basic"
        has_response_schema = isinstance(request.response_schema, dict) and bool(request.response_schema)
        use_function_calling = bool(request.use_function_calling) and has_response_schema

        if is_basic and has_response_schema:
            schema_hint = json.dumps(request.response_schema, ensure_ascii=False, indent=2)
            user_prompt = (
                f"{user_prompt}\n\n"
                f"请严格按照以下 JSON Schema 格式输出，不要输出任何其他内容：\n"
                f"```json\n{schema_hint}\n```"
            )

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": max(0.0, min(float(request.temperature), 2.0)),
        }

        if is_basic and use_function_calling:
            self._attach_function_calling_payload(payload=payload, request=request)
        elif is_basic:
            payload["response_format"] = {"type": "json_object"}
        elif use_function_calling:
            self._attach_function_calling_payload(payload=payload, request=request)
        elif has_response_schema:
            schema_name = str(request.response_schema_name or "writer_output_schema").strip() or "writer_output_schema"
            clean_schema = {
                k: v
                for k, v in request.response_schema.items()
                if not k.startswith("$")
            }
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": bool(request.response_schema_strict),
                    "schema": clean_schema,
                },
            }
        else:
            payload["response_format"] = {"type": "json_object"}
        eff_mt = self._effective_max_tokens(request)
        if eff_mt is not None:
            payload["max_tokens"] = int(eff_mt)
        return payload

    @staticmethod
    def _coerce_target_words(metadata_json: dict[str, Any] | None) -> int | None:
        metadata = dict(metadata_json or {})
        raw = metadata.get("target_words")
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def _attach_function_calling_payload(
        self,
        *,
        payload: dict[str, Any],
        request: TextGenerationRequest,
    ) -> None:
        if not isinstance(request.response_schema, dict) or not request.response_schema:
            return
        function_name = self._resolve_function_name(request)
        function_desc = str(
            request.function_description
            or "Return structured JSON output for this workflow step."
        ).strip()
        clean_params = {
            k: v
            for k, v in request.response_schema.items()
            if not k.startswith("$")
        }
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": function_name,
                    "description": function_desc,
                    "parameters": clean_params,
                },
            }
        ]
        # DashScope 等网关拒绝「强制工具调用」语义（报 tool_choice 不支持 required）
        if self._forced_function_tool_choice_supported():
            payload["tool_choice"] = {
                "type": "function",
                "function": {"name": function_name},
            }
        else:
            payload["tool_choice"] = "auto"

    def _post_chat_payload(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        read_timeout: float,
    ) -> dict[str, Any]:
        resp = httpx.post(
            url,
            headers=headers,
            json=payload,
            timeout=float(read_timeout),
        )
        return self._parse_http_response(resp)

    def _parse_http_response(self, resp: httpx.Response) -> dict[str, Any]:
        try:
            body = resp.json()
        except Exception as exc:
            raise RuntimeError(
                f"LLM 响应非 JSON，status={resp.status_code}"
            ) from exc

        if resp.status_code >= 400:
            self.raise_api_error(status_code=resp.status_code, body=body)
        return body

    @staticmethod
    def raise_api_error(*, status_code: int, body: dict[str, Any] | Any) -> None:
        message = None
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                message = error.get("message")
            elif isinstance(error, str):
                message = error
        err = LLMApiError(
            f"LLM 请求失败 status={status_code}: {message or body}",
            status_code=status_code,
        )
        raise err

    def chat_completions(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
        read_timeout: float | None = None,
    ) -> dict[str, Any]:
        """
        原始 chat/completions 多轮协议（messages 含 assistant/tool 角色）。
        用于一致性审查等「输出函数 + 按需取证工具」的多轮拉取；与单轮 generate 并存。
        """
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "temperature": max(0.0, min(float(temperature), 2.0)),
        }
        if tools:
            payload["tools"] = list(tools)
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
            else:
                payload["tool_choice"] = "auto"
        elif tool_choice is not None:
            payload["tool_choice"] = tool_choice

        if max_tokens is not None:
            mt = max(1, int(max_tokens))
            cap = self.max_output_tokens_cap
            if cap is not None and mt > cap:
                logger.info(
                    "[LLM] chat_completions max_tokens %s 超过厂商上限 %s，已裁剪",
                    mt,
                    cap,
                )
                mt = cap
            payload["max_tokens"] = mt

        to = float(read_timeout) if read_timeout is not None else float(self.timeout_seconds)
        logger.info(
            "[LLM] chat_completions | model=%s messages=%d tools=%s",
            self.model,
            len(messages),
            len(tools or []),
        )
        return self._post_chat_payload(url=url, headers=headers, payload=payload, read_timeout=to)

    def parse_chat_response(self, body: dict[str, Any]) -> TextGenerationResult:
        try:
            choices = body["choices"]
            first = choices[0]
            message = first["message"]
        except Exception as exc:
            raise RuntimeError("LLM 响应格式非法：缺少 choices/message/content") from exc

        json_data = self._parse_response_json_from_message(message)

        if not isinstance(json_data, dict):
            raise RuntimeError("LLM 响应 JSON 顶层必须是对象")

        text = self._extract_primary_text(json_data)

        return TextGenerationResult(
            text=text,
            json_data=json_data,
            model=str(body.get("model") or self.model),
            provider="openai_compatible",
            is_mock=False,
            raw_response_json=body,
            request_metadata_json={},
        )

    @staticmethod
    def _log_completion_usage(*, body: dict[str, Any], meta_tag: str) -> None:
        """记录 finish_reason 与 usage，便于区分 length 截断与模型主动收束。"""
        try:
            choices = body.get("choices")
            if not isinstance(choices, list) or not choices:
                return
            first = choices[0]
            fr = first.get("finish_reason") if isinstance(first, dict) else None
            usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
            logger.info(
                "[LLM] completion_meta | meta=%s finish_reason=%s "
                "completion_tokens=%s prompt_tokens=%s total_tokens=%s",
                meta_tag,
                fr,
                usage.get("completion_tokens"),
                usage.get("prompt_tokens"),
                usage.get("total_tokens"),
            )
        except Exception:
            return

    @staticmethod
    def _writer_json_richness_score(data: dict[str, Any]) -> int:
        """用于在多个可解析候选中选更完整的一份（避免 tool_calls 截断短于 message.content）。"""
        score = 0
        ch = data.get("chapter")
        if isinstance(ch, dict):
            score += len(str(ch.get("content") or ""))
        segs = data.get("segments")
        if isinstance(segs, list):
            for it in segs:
                if isinstance(it, dict):
                    score += len(str(it.get("content") or ""))
        return score

    def _try_parse_content_message_to_dict(self, raw_content: Any) -> dict[str, Any] | None:
        content = raw_content
        if isinstance(content, list):
            text_parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = str(item.get("text") or "").strip()
                    if text:
                        text_parts.append(text)
            content = "\n".join(text_parts).strip()
        if not isinstance(content, str) or not content.strip():
            return None
        try:
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            pass
        extracted = self._extract_json_from_text(content)
        return extracted if isinstance(extracted, dict) else None

    def _parse_response_json_from_message(self, message: dict[str, Any]) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []

        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            for item in tool_calls:
                if not isinstance(item, dict):
                    continue
                func = item.get("function")
                if not isinstance(func, dict):
                    continue
                args = func.get("arguments")
                if not isinstance(args, str) or not args.strip():
                    continue
                try:
                    parsed = json.loads(args)
                except Exception:
                    continue
                if isinstance(parsed, dict):
                    candidates.append(parsed)

        from_content = self._try_parse_content_message_to_dict(message.get("content"))
        if isinstance(from_content, dict):
            candidates.append(from_content)

        if not candidates:
            if isinstance(tool_calls, list) and tool_calls:
                raise RuntimeError(
                    "LLM tool_calls 存在但未返回可解析的 function.arguments，且 message.content 也无合法 JSON"
                )
            raise RuntimeError("LLM 响应 content 为空或不是合法 JSON")

        if len(candidates) > 1:
            best = max(candidates, key=self._writer_json_richness_score)
            scores = [self._writer_json_richness_score(c) for c in candidates]
            if min(scores) != max(scores):
                logger.info(
                    "[LLM] 多路 JSON 候选（tool_calls 与 content 均存在）| "
                    "richness_scores=%s | 选用最高分，避免 arguments 截断导致 chapter 偏短",
                    scores,
                )
            return best

        return candidates[0]

    @staticmethod
    def _extract_json_from_text(text: str) -> dict[str, Any] | None:
        """从 LLM 混合输出中提取最外层 JSON 对象（处理 markdown fence、前后缀文字、截断等）。"""
        import re
        fence = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if fence:
            try:
                parsed = json.loads(fence.group(1).strip())
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        end = -1
        in_string = False
        escape_next = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == "\\":
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end != -1:
            try:
                parsed = json.loads(text[start : end + 1])
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        truncated = text[start:]
        repaired = _repair_truncated_json(truncated)
        if repaired is not None:
            return repaired
        return None

    def _send_with_schema_repair(
        self,
        *,
        request: TextGenerationRequest,
        url: str,
        headers: dict[str, str],
    ) -> tuple[TextGenerationResult, dict[str, Any]]:
        effective_request = request
        repair_limit = max(0, int(request.validation_retries))
        last_errors: list[str] = []
        downgraded_fc = False

        for attempt in range(repair_limit + 1):
            payload = self.build_chat_payload(effective_request)
            try:
                body = self._post_chat_payload(
                    url=url,
                    headers=headers,
                    payload=payload,
                    read_timeout=self._read_timeout_for(effective_request),
                )
                parsed = self.parse_chat_response(body)
            except Exception:
                if effective_request.use_function_calling and not downgraded_fc:
                    effective_request = replace(
                        effective_request,
                        use_function_calling=False,
                    )
                    downgraded_fc = True
                    continue
                raise
            parsed_obj = parsed.json_data
            # Schema 校验前对照 chapter / segments 长度，便于排查 tool_calls 与 content 不一致等问题。
            if isinstance(parsed_obj, dict) and (
                "chapter" in parsed_obj or "segments" in parsed_obj
            ):
                chapter = parsed_obj.get("chapter", {})
                content = chapter.get("content") if isinstance(chapter, dict) else ""
                segments = parsed_obj.get("segments", [])
                segments_join = "".join(
                    str(x.get("content") or "")
                    for x in segments
                    if isinstance(x, dict)
                )
                logger.info(
                    "writer_length_debug | "
                    "chapter_raw_len=%s | "
                    "chapter_non_ws=%s | "
                    "segments_join_raw_len=%s | "
                    "segments_join_non_ws=%s | "
                    "word_count_field=%s",
                    len(content or ""),
                    count_fiction_word_units(content or ""),
                    len(segments_join),
                    count_fiction_word_units(segments_join),
                    parsed_obj.get("word_count"),
                )
            errors = self._validate_response_schema(
                payload=parsed_obj,
                schema=effective_request.response_schema,
            )
            if not errors:
                return (
                    OpenAICompatibleTextProvider._attach_request_metadata(parsed, effective_request),
                    {
                        "schema_validation_applied": bool(effective_request.response_schema),
                        "schema_repair_attempts": attempt,
                        "function_calling_downgraded": downgraded_fc,
                    },
                )
            last_errors = errors
            if effective_request.use_function_calling and not downgraded_fc:
                effective_request = replace(
                    effective_request,
                    use_function_calling=False,
                )
                downgraded_fc = True
                continue
            if attempt >= repair_limit:
                break
            effective_request = self._build_repair_request(
                request=effective_request,
                validation_errors=errors,
                previous_output=parsed.json_data,
                attempt=attempt + 1,
            )

        raise ResponseSchemaValidationError(
            "LLM 输出未通过 schema 校验: " + "; ".join(last_errors[:5]),
            errors=list(last_errors[:20]),
            json_data=dict(parsed.json_data or {}),
        )

    def _validate_request_input(self, request: TextGenerationRequest) -> dict[str, Any]:
        if not isinstance(request.input_schema, dict) or not request.input_schema:
            return {
                "applied": False,
                "schema_name": None,
                "warnings": [],
            }
        schema_name = str(request.input_schema_name or "input_schema").strip() or "input_schema"
        payload = self._resolve_input_payload(request=request)
        errors = self._validate_response_schema(
            payload=payload,
            schema=request.input_schema,
        )
        if errors and bool(request.input_schema_strict):
            raise RuntimeError(
                "LLM 输入未通过 schema 校验"
                f"({schema_name}): "
                + "; ".join(errors[:5])
            )
        return {
            "applied": True,
            "schema_name": schema_name,
            "strict": bool(request.input_schema_strict),
            "warnings": list(errors),
        }

    @staticmethod
    def _resolve_input_payload(request: TextGenerationRequest) -> Any:
        if request.input_payload is not None:
            return request.input_payload
        text = str(request.user_prompt or "").strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except Exception as exc:
            raise RuntimeError("LLM 输入 schema 校验失败：user_prompt 不是合法 JSON") from exc

    def _should_apply_prompt_guard(self, request: TextGenerationRequest) -> bool:
        if not self.prompt_guard_enabled:
            return False
        metadata = dict(request.metadata_json or {})
        if bool(metadata.get("disable_prompt_guard")):
            return False
        workflow = str(metadata.get("workflow") or "").strip().lower()
        if workflow == "context_compression":
            # 避免压缩调用自身时递归触发 guard。
            return False
        return True

    def _build_repair_request(
        self,
        *,
        request: TextGenerationRequest,
        validation_errors: list[str],
        previous_output: dict[str, Any],
        attempt: int,
    ) -> TextGenerationRequest:
        schema_json = json.dumps(request.response_schema or {}, ensure_ascii=False)
        errors_text = "\n".join(f"- {item}" for item in validation_errors[:8])
        previous_json = json.dumps(previous_output, ensure_ascii=False)
        repair_suffix = (
            "\n\n# 校验失败自动修复指令\n"
            f"修复轮次: {attempt}\n"
            "你上一轮输出未通过 JSON Schema 校验，请只返回一个合法 JSON 对象，不要输出解释。\n"
            "必须满足以下 schema：\n"
            f"{schema_json}\n"
            "校验错误：\n"
            f"{errors_text}\n"
            "上一轮输出：\n"
            f"{previous_json}\n"
        )
        return replace(
            request,
            user_prompt=str(request.user_prompt or "") + repair_suffix,
            temperature=min(0.3, float(request.temperature)),
            metadata_json={
                **dict(request.metadata_json or {}),
                "schema_repair_attempt": int(attempt),
            },
        )

    def _apply_prompt_guard(
        self,
        *,
        request: TextGenerationRequest,
        force: bool,
    ) -> tuple[TextGenerationRequest, dict[str, Any]]:
        input_budget = self._resolve_input_budget(request)
        before_tokens = self._estimate_prompt_tokens(request)
        if before_tokens <= input_budget and not force:
            return request, {
                "applied": False,
                "attempts": 0,
                "before_tokens": before_tokens,
                "after_tokens": before_tokens,
                "input_budget": input_budget,
                "reason": "within_budget",
            }

        system_tokens = estimate_token_count(str(request.system_prompt or ""))
        target_user_budget = max(
            64,
            input_budget - system_tokens - self.prompt_guard_overhead_tokens,
        )
        query = self._resolve_guard_query(request)

        current_text = str(request.user_prompt or "")
        attempts = max(2, self.prompt_guard_max_attempts) if force else self.prompt_guard_max_attempts
        llm_used = False
        method = "none"

        for idx in range(attempts):
            shrink_ratio = 0.78 if force else 0.9
            attempt_budget = max(64, int(target_user_budget * (shrink_ratio ** idx)))
            current_text, method, used_llm = self._compress_user_prompt_by_llm(
                text=current_text,
                query=query,
                token_budget=attempt_budget,
            )
            llm_used = llm_used or used_llm

            candidate = replace(request, user_prompt=current_text)
            if self._estimate_prompt_tokens(candidate) <= input_budget:
                after_tokens = self._estimate_prompt_tokens(candidate)
                return (
                    candidate,
                    {
                        "applied": True,
                        "attempts": idx + 1,
                        "before_tokens": before_tokens,
                        "after_tokens": after_tokens,
                        "input_budget": input_budget,
                        "llm_used": llm_used,
                        "method": method,
                        "reason": "compressed_to_fit",
                    },
                )

        # 最后兜底：按预算做本地硬裁剪，保证不会无限重试。
        fallback_budget = max(64, target_user_budget)
        fallback_text, fallback_method = compress_text_to_budget(
            current_text,
            token_budget=fallback_budget,
            query=query,
            fallback_summary=None,
        )
        candidate = replace(request, user_prompt=fallback_text)
        after_tokens = self._estimate_prompt_tokens(candidate)
        return (
            candidate,
            {
                "applied": True,
                "attempts": attempts,
                "before_tokens": before_tokens,
                "after_tokens": after_tokens,
                "input_budget": input_budget,
                "llm_used": llm_used,
                "method": fallback_method,
                "reason": "fallback_local_truncate",
            },
        )

    def _compress_user_prompt_by_llm(
        self,
        *,
        text: str,
        query: str,
        token_budget: int,
    ) -> tuple[str, str, bool]:
        # 懒加载：避免 packages.llm.text_generation ↔ hybrid_compressor 与 working_memory 包循环导入
        from packages.memory.working_memory.hybrid_compressor import HybridContextCompressor

        compressor = HybridContextCompressor(
            text_provider=self,
            enable_llm=True,
            llm_trigger_ratio=1.0,
            llm_min_gain_ratio=0.0,
            llm_max_input_chars=self.prompt_guard_llm_max_input_chars,
        )
        result = compressor.compress(
            text=text,
            token_budget=max(64, int(token_budget)),
            query=query,
            summary_hint=None,
            allow_llm=True,
        )
        content = str(result.text or "").strip()
        if not content:
            fallback_text, fallback_method = compress_text_to_budget(
                text,
                token_budget=max(64, int(token_budget)),
                query=query,
                fallback_summary=None,
            )
            return fallback_text, fallback_method, False
        return content, str(result.method), bool(result.llm_used)

    @staticmethod
    def _extract_primary_text(json_data: dict[str, Any]) -> str:
        for key in ("content", "notes", "summary", "title"):
            value = str(json_data.get(key) or "").strip()
            if value:
                return value
        serialized = json.dumps(json_data, ensure_ascii=False)
        if not serialized or serialized == "{}":
            raise RuntimeError("LLM 响应 JSON 为空对象")
        return serialized

    def _validate_response_schema(
        self,
        *,
        payload: Any,
        schema: dict[str, Any] | None,
    ) -> list[str]:
        if not isinstance(schema, dict) or not schema:
            return []
        issues: list[str] = []
        self._validate_schema_node(
            schema=schema,
            payload=payload,
            path="$",
            issues=issues,
        )
        return issues

    def _validate_schema_node(
        self,
        *,
        schema: dict[str, Any],
        payload: Any,
        path: str,
        issues: list[str],
    ) -> None:
        expected_type = schema.get("type")
        if expected_type is not None and not self._schema_type_match(payload, expected_type):
            issues.append(f"{path}: type 不匹配，期望 {expected_type}，实际 {type(payload).__name__}")
            return

        enum_values = schema.get("enum")
        if isinstance(enum_values, list) and payload not in enum_values:
            issues.append(f"{path}: 值不在 enum 中: {payload!r}")

        if isinstance(payload, str):
            min_len = schema.get("minLength")
            if isinstance(min_len, int) and len(payload) < min_len:
                issues.append(f"{path}: 长度不足，最小 {min_len}")

        if isinstance(payload, (int, float)) and not isinstance(payload, bool):
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            if isinstance(minimum, (int, float)) and payload < minimum:
                issues.append(f"{path}: 小于最小值 {minimum}")
            if isinstance(maximum, (int, float)) and payload > maximum:
                issues.append(f"{path}: 大于最大值 {maximum}")

        if isinstance(payload, dict):
            properties = schema.get("properties") or {}
            required = schema.get("required") or []
            for name in required:
                if name not in payload:
                    issues.append(f"{path}: 缺少必填字段: {name}")
            for key, value in payload.items():
                key_path = f"{path}.{key}"
                if key in properties and isinstance(properties[key], dict):
                    self._validate_schema_node(
                        schema=properties[key],
                        payload=value,
                        path=key_path,
                        issues=issues,
                    )
                    continue
                additional = schema.get("additionalProperties", True)
                if additional is False:
                    issues.append(f"{key_path}: 不允许额外字段")
                elif isinstance(additional, dict):
                    self._validate_schema_node(
                        schema=additional,
                        payload=value,
                        path=key_path,
                        issues=issues,
                    )
            return

        if isinstance(payload, list):
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for idx, item in enumerate(payload):
                    self._validate_schema_node(
                        schema=item_schema,
                        payload=item,
                        path=f"{path}[{idx}]",
                        issues=issues,
                    )

    @staticmethod
    def _schema_type_match(payload: Any, expected_type: str | list[str]) -> bool:
        candidates = [expected_type] if isinstance(expected_type, str) else list(expected_type)
        for item in candidates:
            if item == "object" and isinstance(payload, dict):
                return True
            if item == "array" and isinstance(payload, list):
                return True
            if item == "string" and isinstance(payload, str):
                return True
            if item == "boolean" and isinstance(payload, bool):
                return True
            if item == "integer" and isinstance(payload, int) and not isinstance(payload, bool):
                return True
            if item == "number" and isinstance(payload, (int, float)) and not isinstance(payload, bool):
                return True
            if item == "null" and payload is None:
                return True
        return False

    @staticmethod
    def _resolve_function_name(request: TextGenerationRequest) -> str:
        raw = str(request.function_name or request.response_schema_name or "writer_output").strip()
        if not raw:
            raw = "writer_output"
        out_chars: list[str] = []
        for ch in raw:
            if ch.isalnum() or ch in {"_", "-"}:
                out_chars.append(ch)
            else:
                out_chars.append("_")
        normalized = "".join(out_chars).strip("_")
        if not normalized:
            normalized = "writer_output"
        return normalized[:64]

    def _effective_max_tokens(self, request: TextGenerationRequest) -> int | None:
        """按厂商上限裁剪 max_tokens（如通义网关要求 ≤8192），避免 400 InvalidParameter。"""
        if request.max_tokens is None:
            return None
        mt = max(1, int(request.max_tokens))
        cap = self.max_output_tokens_cap
        if cap is not None and mt > cap:
            logger.info(
                "[LLM] max_tokens 请求值 %s 超过厂商上限 %s，已裁剪",
                mt,
                cap,
            )
            mt = cap
        return mt

    def _resolve_input_budget(self, request: TextGenerationRequest) -> int:
        eff = self._effective_max_tokens(request)
        reserve = int(eff) if eff is not None else int(self.prompt_guard_output_reserve_tokens)
        reserve = max(128, reserve)
        return max(512, self.model_context_window_tokens - reserve)

    def _estimate_prompt_tokens(self, request: TextGenerationRequest) -> int:
        system_tokens = estimate_token_count(str(request.system_prompt or ""))
        user_tokens = estimate_token_count(str(request.user_prompt or ""))
        return system_tokens + user_tokens + self.prompt_guard_overhead_tokens

    @staticmethod
    def _resolve_guard_query(request: TextGenerationRequest) -> str:
        metadata = dict(request.metadata_json or {})
        for key in ("writing_goal", "query", "goal", "intent"):
            value = str(metadata.get(key) or "").strip()
            if value:
                return value
        text = str(request.user_prompt or "").strip()
        return text[:200]

    def _is_context_length_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return any(hint in message for hint in self._CONTEXT_ERROR_HINTS)

    @staticmethod
    def _attach_request_metadata(
        result: TextGenerationResult,
        request: TextGenerationRequest,
    ) -> TextGenerationResult:
        return TextGenerationResult(
            text=result.text,
            json_data=dict(result.json_data or {}),
            model=result.model,
            provider=result.provider,
            is_mock=result.is_mock,
            raw_response_json=dict(result.raw_response_json or {}),
            request_metadata_json=dict(request.metadata_json or {}),
        )

    @staticmethod
    def _with_prompt_guard(
        result: TextGenerationResult,
        *,
        prompt_guard: dict[str, Any],
    ) -> TextGenerationResult:
        raw = dict(result.raw_response_json or {})
        raw["prompt_guard"] = dict(prompt_guard or {})
        return TextGenerationResult(
            text=result.text,
            json_data=dict(result.json_data or {}),
            model=result.model,
            provider=result.provider,
            is_mock=result.is_mock,
            raw_response_json=raw,
            request_metadata_json=dict(result.request_metadata_json or {}),
        )

    @staticmethod
    def _with_input_validation(
        result: TextGenerationResult,
        *,
        input_validation: dict[str, Any],
    ) -> TextGenerationResult:
        raw = dict(result.raw_response_json or {})
        raw["input_validation"] = dict(input_validation or {})
        return TextGenerationResult(
            text=result.text,
            json_data=dict(result.json_data or {}),
            model=result.model,
            provider=result.provider,
            is_mock=result.is_mock,
            raw_response_json=raw,
            request_metadata_json=dict(result.request_metadata_json or {}),
        )
