"""一致性审查：多轮 tool calling（按需 fetch_consistency_evidence + 最终 consistency_review_output）。"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from packages.llm.text_generation.base import TextGenerationResult
from packages.llm.text_generation.openai_compatible import OpenAICompatibleTextProvider
from packages.llm.text_generation.schema_errors import ResponseSchemaValidationError

logger = logging.getLogger("writeragent.consistency_review")

FETCH_CONSISTENCY_EVIDENCE = "fetch_consistency_evidence"


def _schema_repair_user_content(
    *,
    output_schema: dict[str, Any],
    validation_errors: list[str],
    previous_output: dict[str, Any],
    repair_round: int,
) -> str:
    """构造与单轮 _build_repair_request 对齐的修复提示（写入 user 消息）。"""
    schema_json = json.dumps(output_schema, ensure_ascii=False)
    errors_text = "\n".join(f"- {item}" for item in validation_errors[:8])
    previous_json = json.dumps(previous_output, ensure_ascii=False)
    return (
        "\n\n# 校验失败自动修复指令\n"
        f"修复轮次: {repair_round}\n"
        "你上一轮通过 consistency_review_output 提交的 JSON 未通过 Schema 校验。"
        "请再次调用 consistency_review_output，仅修正字段，勿臆造证据。\n"
        "必须满足以下 schema：\n"
        f"{schema_json}\n"
        "校验错误：\n"
        f"{errors_text}\n"
        "上一轮输出：\n"
        f"{previous_json}\n"
    )


def _output_tool_definition(
    *,
    output_schema: dict[str, Any],
    function_name: str,
    description: str,
) -> dict[str, Any]:
    clean_params = {k: v for k, v in output_schema.items() if not str(k).startswith("$")}
    return {
        "type": "function",
        "function": {
            "name": function_name,
            "description": description,
            "parameters": clean_params,
        },
    }


def _fetch_tool_definition() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": FETCH_CONSISTENCY_EVIDENCE,
            "description": (
                "当证据包中未包含但必须核对时，按 UUID 从项目库拉取单条实体。"
                "scope: character | world_entry | timeline_event | foreshadowing。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": [
                            "character",
                            "world_entry",
                            "timeline_event",
                            "foreshadowing",
                        ],
                    },
                    "entity_id": {
                        "type": "string",
                        "description": "实体 UUID",
                    },
                },
                "required": ["scope", "entity_id"],
            },
        },
    }


def _validate_with_provider(
    provider: Any,
    *,
    payload: dict[str, Any],
    schema: dict[str, Any],
) -> list[str]:
    fn = getattr(provider, "_validate_response_schema", None)
    if not callable(fn):
        return []
    return list(fn(payload=payload, schema=schema) or [])


def run_consistency_review_tool_loop(
    provider: Any,
    *,
    system_prompt: str,
    user_json: str,
    output_schema: dict[str, Any],
    output_function_name: str,
    output_description: str,
    fetch_handler: Callable[[str, str], dict[str, Any]],
    max_rounds: int = 6,
    max_fetches: int = 3,
    validation_retries: int = 1,
    temperature: float = 0.1,
    max_tokens: int | None = 1200,
    read_timeout: float | None = None,
    metadata_tag: str = "consistency_tool_loop",
    entity_id_allowlist: set[str] | None = None,
) -> TextGenerationResult:
    """
    多轮 chat/completions：模型可多次调用 fetch，最后必须调用输出函数提交审查 JSON。

    - max_fetches：fetch_consistency_evidence 实际拉库次数上限，超出则返回 budget 提示。
    - validation_retries：与单轮 generate 一致，输出 JSON 未过 schema 时追加 user 修复提示并重试；
      失败次数超过该值则抛出 ResponseSchemaValidationError。

    provider 须实现 ``chat_completions(**kwargs) -> dict``（见 OpenAICompatibleTextProvider）。
    若 provider 实现 ``_validate_response_schema``，则对最终输出做与单轮相同的校验。

    entity_id_allowlist：非 None 时仅允许拉取白名单内 UUID（一档审查服务端证据策略）；None 表示不限制。
    """
    tools = [
        _output_tool_definition(
            output_schema=output_schema,
            function_name=output_function_name,
            description=output_description,
        ),
        _fetch_tool_definition(),
    ]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_json},
    ]

    final_json: dict[str, Any] | None = None
    last_raw: dict[str, Any] = {}
    last_bad_json: dict[str, Any] | None = None
    invalid_output_submissions = 0
    fetch_count = 0
    repair_round = 0

    for round_idx in range(max(1, int(max_rounds))):
        body = provider.chat_completions(
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=temperature,
            max_tokens=max_tokens,
            read_timeout=read_timeout,
        )
        last_raw = dict(body)
        try:
            choices = body.get("choices") or []
            msg = dict(choices[0].get("message") or {})
        except (IndexError, TypeError, ValueError) as exc:
            raise RuntimeError("LLM 响应缺少 choices[0].message") from exc

        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": msg.get("content"),
                "tool_calls": tool_calls,
            }
            messages.append(assistant_msg)

            pending_repair: str | None = None

            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function")
                if not isinstance(fn, dict):
                    continue
                name = str(fn.get("name") or "").strip()
                args_raw = str(fn.get("arguments") or "").strip() or "{}"
                tc_id = str(tc.get("id") or "").strip() or f"call_{round_idx}"
                try:
                    args = json.loads(args_raw)
                except json.JSONDecodeError:
                    args = {}

                if name == FETCH_CONSISTENCY_EVIDENCE:
                    scope = str(args.get("scope") or "").strip()
                    eid = str(args.get("entity_id") or "").strip()
                    if entity_id_allowlist is not None and eid not in entity_id_allowlist:
                        result = {
                            "error": "entity_not_allowlisted",
                            "message": (
                                "该 entity_id 不在服务端证据白名单；请仅使用 state.review_context 与 "
                                "state.review_evidence_pack 已给出的实体与片段完成审查。"
                            ),
                            "entity_id": eid,
                        }
                        logger.warning(
                            "[%s] fetch denied non-allowlisted id=%s",
                            metadata_tag,
                            eid,
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": json.dumps(result, ensure_ascii=False),
                            }
                        )
                        continue
                    if fetch_count >= max(0, int(max_fetches)):
                        result = {
                            "error": "fetch_budget_exhausted",
                            "message": (
                                f"已达最大取证次数 {max_fetches}，请基于已有证据调用 "
                                f"{output_function_name}。"
                            ),
                            "max_fetches": max_fetches,
                        }
                        logger.warning(
                            "[%s] fetch budget exhausted (round=%d)",
                            metadata_tag,
                            round_idx + 1,
                        )
                    else:
                        fetch_count += 1
                        result = fetch_handler(scope, eid)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
                elif name == output_function_name:
                    if not isinstance(args, dict) or not args:
                        invalid_output_submissions += 1
                        last_bad_json = dict(args) if isinstance(args, dict) else {}
                        if invalid_output_submissions > max(0, int(validation_retries)):
                            raise ResponseSchemaValidationError(
                                "一致性审查输出无效（空参数）且超过修复次数上限",
                                errors=["consistency_review_output arguments 为空或无法解析"],
                                json_data=last_bad_json,
                            )
                        repair_round = invalid_output_submissions
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": json.dumps(
                                    {"status": "rejected", "reason": "empty_or_unparsed_arguments"},
                                    ensure_ascii=False,
                                ),
                            }
                        )
                        pending_repair = _schema_repair_user_content(
                            output_schema=output_schema,
                            validation_errors=["consistency_review_output 的 arguments 为空或不是对象"],
                            previous_output={},
                            repair_round=repair_round,
                        )
                        continue

                    errors = _validate_with_provider(
                        provider,
                        payload=args,
                        schema=output_schema,
                    )
                    if errors:
                        invalid_output_submissions += 1
                        last_bad_json = dict(args)
                        if invalid_output_submissions > max(0, int(validation_retries)):
                            raise ResponseSchemaValidationError(
                                "LLM 输出未通过 schema 校验: " + "; ".join(errors[:5]),
                                errors=list(errors[:20]),
                                json_data=last_bad_json,
                            )
                        repair_round = invalid_output_submissions
                        logger.info(
                            "[%s] output schema rejected round=%d errors=%s",
                            metadata_tag,
                            round_idx + 1,
                            errors[:3],
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": json.dumps(
                                    {"status": "schema_rejected", "errors": errors[:8]},
                                    ensure_ascii=False,
                                ),
                            }
                        )
                        pending_repair = _schema_repair_user_content(
                            output_schema=output_schema,
                            validation_errors=errors,
                            previous_output=args,
                            repair_round=repair_round,
                        )
                    else:
                        final_json = args
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": json.dumps({"status": "accepted"}, ensure_ascii=False),
                            }
                        )

            if final_json is not None:
                logger.info(
                    "[%s] tool loop done round=%d output=%s",
                    metadata_tag,
                    round_idx + 1,
                    output_function_name,
                )
                break
            if pending_repair:
                messages.append({"role": "user", "content": pending_repair})
            logger.info("[%s] tool loop round=%d fetch_only_or_repair", metadata_tag, round_idx + 1)
            continue

        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            try_parse_fn = getattr(provider, "_try_parse_content_message_to_dict", None)
            try_parse = try_parse_fn(content) if callable(try_parse_fn) else None
            if isinstance(try_parse, dict) and try_parse.get("overall_status") is not None:
                errors = _validate_with_provider(
                    provider,
                    payload=try_parse,
                    schema=output_schema,
                )
                if errors:
                    invalid_output_submissions += 1
                    last_bad_json = dict(try_parse)
                    if invalid_output_submissions > max(0, int(validation_retries)):
                        raise ResponseSchemaValidationError(
                            "LLM 输出未通过 schema 校验: " + "; ".join(errors[:5]),
                            errors=list(errors[:20]),
                            json_data=last_bad_json,
                        )
                    repair_round = invalid_output_submissions
                    messages.append(
                        {
                            "role": "user",
                            "content": _schema_repair_user_content(
                                output_schema=output_schema,
                                validation_errors=errors,
                                previous_output=try_parse,
                                repair_round=repair_round,
                            ),
                        }
                    )
                    logger.info(
                        "[%s] content path schema rejected round=%d",
                        metadata_tag,
                        round_idx + 1,
                    )
                    continue
                final_json = try_parse
                break

        logger.warning("[%s] tool loop round=%d no tool_calls and no parseable content", metadata_tag, round_idx + 1)
        break

    if not isinstance(final_json, dict):
        if last_bad_json:
            raise ResponseSchemaValidationError(
                "多轮审查未得到通过校验的 consistency_review_output",
                errors=["未在轮次上限内产出合法输出"],
                json_data=last_bad_json,
            )
        raise RuntimeError("多轮审查未得到有效的 consistency_review_output")

    text = str(OpenAICompatibleTextProvider._extract_primary_text(final_json))
    return TextGenerationResult(
        text=text,
        json_data=final_json,
        model=str(last_raw.get("model") or getattr(provider, "model", "")),
        provider="openai_compatible_tool_loop",
        is_mock=False,
        raw_response_json=last_raw,
    )
