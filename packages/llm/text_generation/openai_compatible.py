from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import httpx

from packages.core.utils import (
    compress_text_to_budget,
    ensure_non_empty_string,
    estimate_token_count,
)
from packages.llm.text_generation.base import (
    TextGenerationProvider,
    TextGenerationRequest,
    TextGenerationResult,
)
from packages.llm.text_generation.mock_provider import MockTextGenerationProvider
from packages.memory.working_memory.hybrid_compressor import HybridContextCompressor


class OpenAICompatibleTextProvider(TextGenerationProvider):
    """
    OpenAI 兼容文本生成 Provider。

    说明：
    - 当前阶段默认旁路到 Mock（按项目约束，不直接调用真实模型）。
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
        bypass_to_mock: bool = True,
        fallback_to_mock_on_error: bool = True,
        prompt_guard_enabled: bool = True,
        model_context_window_tokens: int = 128000,
        prompt_guard_output_reserve_tokens: int = 4096,
        prompt_guard_overhead_tokens: int = 256,
        prompt_guard_max_attempts: int = 2,
        prompt_guard_llm_max_input_chars: int = 12000,
        mock_provider: MockTextGenerationProvider | None = None,
    ) -> None:
        self.api_key = ensure_non_empty_string(api_key, field_name="api_key")
        self.model = ensure_non_empty_string(model, field_name="model")
        self.base_url = ensure_non_empty_string(base_url, field_name="base_url").rstrip("/")
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.bypass_to_mock = bool(bypass_to_mock)
        self.fallback_to_mock_on_error = bool(fallback_to_mock_on_error)
        self.mock_provider = mock_provider or MockTextGenerationProvider()

        self.prompt_guard_enabled = bool(prompt_guard_enabled)
        self.model_context_window_tokens = max(2048, int(model_context_window_tokens))
        self.prompt_guard_output_reserve_tokens = max(128, int(prompt_guard_output_reserve_tokens))
        self.prompt_guard_overhead_tokens = max(64, int(prompt_guard_overhead_tokens))
        self.prompt_guard_max_attempts = max(1, int(prompt_guard_max_attempts))
        self.prompt_guard_llm_max_input_chars = max(500, int(prompt_guard_llm_max_input_chars))

    def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        effective_request = request
        input_validation = self._validate_request_input(request)
        prompt_guard = {"applied": False, "attempts": 0, "reason": "disabled_or_not_needed"}
        if self._should_apply_prompt_guard(request):
            effective_request, prompt_guard = self._apply_prompt_guard(
                request=request,
                force=False,
            )

        payload = self.build_chat_payload(effective_request)

        # 当前开发阶段默认旁路到 Mock，避免依赖真实大模型服务。
        if self.bypass_to_mock:
            mock_result = self.mock_provider.generate(effective_request)
            return TextGenerationResult(
                text=mock_result.text,
                json_data=mock_result.json_data,
                model=self.model,
                provider="openai_compatible(mock_bypass)",
                is_mock=True,
                raw_response_json={
                    "payload": payload,
                    "prompt_guard": prompt_guard,
                    "input_validation": input_validation,
                    "mock_output": mock_result.raw_response_json,
                },
            )

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            parsed, runtime_meta = self._send_with_schema_repair(
                request=effective_request,
                url=url,
                headers=headers,
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
            retry_payload: dict[str, Any] | None = None
            retry_applied = False
            if self._should_apply_prompt_guard(effective_request) and self._is_context_length_error(exc):
                retry_request, retry_guard = self._apply_prompt_guard(
                    request=effective_request,
                    force=True,
                )
                if retry_request.user_prompt != effective_request.user_prompt:
                    retry_payload = self.build_chat_payload(retry_request)
                    retry_applied = True
                    try:
                        parsed, runtime_meta = self._send_with_schema_repair(
                            request=retry_request,
                            url=url,
                            headers=headers,
                        )
                        merged_guard = {
                            **prompt_guard,
                            **retry_guard,
                            **runtime_meta,
                            "second_retry_applied": True,
                        }
                        with_guard = self._with_prompt_guard(parsed, prompt_guard=merged_guard)
                        return self._with_input_validation(with_guard, input_validation=input_validation)
                    except Exception as retry_exc:
                        exc = retry_exc
                        payload = retry_payload
                        prompt_guard = {
                            **prompt_guard,
                            **retry_guard,
                            "second_retry_applied": True,
                            "second_retry_failed": True,
                        }

            if not self.fallback_to_mock_on_error:
                raise

            fallback = self.mock_provider.generate(effective_request)
            return TextGenerationResult(
                text=fallback.text,
                json_data=fallback.json_data,
                model=self.model,
                provider="openai_compatible(mock_fallback_after_error)",
                is_mock=True,
                raw_response_json={
                    "payload": payload,
                    "retry_payload": retry_payload,
                    "retry_applied": retry_applied,
                    "prompt_guard": prompt_guard,
                    "input_validation": input_validation,
                    "error": str(exc),
                    "mock_output": fallback.raw_response_json,
                },
            )

    def build_chat_payload(self, request: TextGenerationRequest) -> dict[str, Any]:
        system_prompt = ensure_non_empty_string(
            request.system_prompt,
            field_name="system_prompt",
        )
        user_prompt = ensure_non_empty_string(
            request.user_prompt,
            field_name="user_prompt",
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": max(0.0, min(float(request.temperature), 2.0)),
        }
        if (
            bool(request.use_function_calling)
            and isinstance(request.response_schema, dict)
            and request.response_schema
        ):
            function_name = self._resolve_function_name(request)
            function_desc = str(
                request.function_description
                or "Return structured JSON output for this workflow step."
            ).strip()
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": function_name,
                        "description": function_desc,
                        "parameters": request.response_schema,
                    },
                }
            ]
            payload["tool_choice"] = {
                "type": "function",
                "function": {"name": function_name},
            }
        elif isinstance(request.response_schema, dict) and request.response_schema:
            schema_name = str(request.response_schema_name or "writer_output_schema").strip() or "writer_output_schema"
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": bool(request.response_schema_strict),
                    "schema": request.response_schema,
                },
            }
        else:
            payload["response_format"] = {"type": "json_object"}
        if request.max_tokens is not None:
            payload["max_tokens"] = int(request.max_tokens)
        return payload

    def _post_chat_payload(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        resp = httpx.post(
            url,
            headers=headers,
            json=payload,
            timeout=self.timeout_seconds,
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
        raise RuntimeError(
            f"LLM 请求失败 status={status_code}: {message or body}"
        )

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
        )

    def _parse_response_json_from_message(self, message: dict[str, Any]) -> dict[str, Any]:
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
                except Exception as exc:
                    raise RuntimeError("LLM function arguments 不是合法 JSON") from exc
                if isinstance(parsed, dict):
                    return parsed
            raise RuntimeError("LLM tool_calls 存在但未返回可解析的 function.arguments")

        content = message.get("content")
        if isinstance(content, list):
            text_parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = str(item.get("text") or "").strip()
                    if text:
                        text_parts.append(text)
            content = "\n".join(text_parts).strip()
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("LLM 响应 content 为空")
        try:
            return json.loads(content)
        except Exception as exc:
            raise RuntimeError("LLM 响应 content 不是合法 JSON") from exc

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

        for attempt in range(repair_limit + 1):
            payload = self.build_chat_payload(effective_request)
            body = self._post_chat_payload(url=url, headers=headers, payload=payload)
            parsed = self.parse_chat_response(body)
            errors = self._validate_response_schema(
                payload=parsed.json_data,
                schema=effective_request.response_schema,
            )
            if not errors:
                return (
                    parsed,
                    {
                        "schema_validation_applied": bool(effective_request.response_schema),
                        "schema_repair_attempts": attempt,
                    },
                )
            last_errors = errors
            if attempt >= repair_limit:
                break
            effective_request = self._build_repair_request(
                request=effective_request,
                validation_errors=errors,
                previous_output=parsed.json_data,
                attempt=attempt + 1,
            )

        raise RuntimeError(
            "LLM 输出未通过 schema 校验: " + "; ".join(last_errors[:5])
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

    def _resolve_input_budget(self, request: TextGenerationRequest) -> int:
        reserve = (
            int(request.max_tokens)
            if request.max_tokens is not None
            else self.prompt_guard_output_reserve_tokens
        )
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
        )
