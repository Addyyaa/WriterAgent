from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import httpx

from packages.llm.text_generation.runtime_config import TextGenerationRuntimeConfig
from packages.tools.system_tools.local_project_list_tool import LocalProjectListTool


def _chat_completions_url(base_url: str) -> str:
    return f"{str(base_url).rstrip('/')}/chat/completions"


def _call_llm_with_tool(*, cfg: TextGenerationRuntimeConfig, tool: LocalProjectListTool) -> dict:
    url = _chat_completions_url(cfg.base_url)
    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
    }
    system_prompt = "你是项目分析助手。先调用工具获取项目列表，再给出 JSON 结论。"
    user_prompt = "请先调用 get_local_projects 获取已有项目列表，再输出 JSON：包含 overview、project_titles、notes。"
    tool_schema = {
        "type": "function",
        "function": {
            "name": "get_local_projects",
            "description": "从本地数据库读取当前项目列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50}
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    }

    first_payload = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "tools": [tool_schema],
        "tool_choice": "auto",
    }
    first_resp = httpx.post(url, headers=headers, json=first_payload, timeout=cfg.timeout_seconds)
    first_resp.raise_for_status()
    first_body = first_resp.json()
    first_msg = dict(first_body.get("choices", [{}])[0].get("message") or {})
    tool_calls = list(first_msg.get("tool_calls") or [])
    if not tool_calls:
        raise RuntimeError("LLM 未调用 get_local_projects 工具")

    first_call = dict(tool_calls[0] or {})
    first_func = dict(first_call.get("function") or {})
    first_name = str(first_func.get("name") or "").strip()
    if first_name != "get_local_projects":
        raise RuntimeError(f"LLM 调用了非预期工具: {first_name}")

    args_raw = str(first_func.get("arguments") or "{}").strip()
    args = json.loads(args_raw) if args_raw else {}
    limit = int(args.get("limit", 20)) if isinstance(args, dict) else 20
    tool_result = tool.run(limit=limit)

    second_payload = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
            {
                "role": "assistant",
                "content": first_msg.get("content") or "",
                "tool_calls": tool_calls,
            },
            {
                "role": "tool",
                "tool_call_id": str(first_call.get("id") or ""),
                "name": "get_local_projects",
                "content": json.dumps(tool_result, ensure_ascii=False),
            },
            {
                "role": "user",
                "content": "请基于工具返回结果，输出 JSON：overview(string)、project_titles(string[])、notes(string)。",
            },
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    second_resp = httpx.post(url, headers=headers, json=second_payload, timeout=cfg.timeout_seconds)
    second_resp.raise_for_status()
    second_body = second_resp.json()
    second_msg = dict(second_body.get("choices", [{}])[0].get("message") or {})
    content = second_msg.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("LLM 最终响应为空")
    llm_output = json.loads(content)
    if not isinstance(llm_output, dict):
        raise RuntimeError("LLM 最终输出不是 JSON 对象")
    return {
        "tool_call": {
            "name": first_name,
            "arguments": args if isinstance(args, dict) else {},
            "result": tool_result,
        },
        "llm_output": llm_output,
    }


def main() -> None:
    cfg = TextGenerationRuntimeConfig.from_env()
    if not str(cfg.api_key or "").strip():
        raise RuntimeError("WRITER_LLM_API_KEY 未配置，无法执行 LLM 工具调用测试")
    tool = LocalProjectListTool()
    result = _call_llm_with_tool(cfg=cfg, tool=tool)

    log_payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "task": "llm_tool_call_local_project_list",
        "llm_provider": "openai_compatible_raw_http",
        "llm_model": cfg.model,
        "tool_call": dict(result.get("tool_call") or {}),
        "llm_output": dict(result.get("llm_output") or {}),
    }

    log_path = Path("data/worker.log")
    with log_path.open("a", encoding="utf-8") as f:
        f.write("=== LLM TOOL CALL PROJECT LIST START ===\n")
        f.write(json.dumps(log_payload, ensure_ascii=False) + "\n")
        f.write("=== LLM TOOL CALL PROJECT LIST END ===\n")

    print(json.dumps(log_payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
