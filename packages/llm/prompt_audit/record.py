"""将发往 LLM 的 system/user 上下文落库（或 JSONL 兜底），供运维按 llm_task_id 查询。"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from packages.core.config import env_bool, env_str

logger = logging.getLogger("writeragent.llm_audit")


def is_llm_prompt_audit_enabled() -> bool:
    return env_bool("WRITER_LLM_PROMPT_AUDIT_ENABLED", True)


def _jsonl_fallback_path() -> Path:
    root = Path(__file__).resolve().parents[3]
    return root / "data" / "llm_prompt_audit.jsonl"


def _append_jsonl(row: dict[str, Any]) -> None:
    path = _jsonl_fallback_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("llm prompt audit JSONL 写入失败: %s", exc)


def _parse_uuid(val: Any) -> uuid.UUID | None:
    if val is None:
        return None
    try:
        return uuid.UUID(str(val).strip())
    except ValueError:
        return None


def record_llm_prompt_audit(
    *,
    llm_task_id: str,
    system_prompt: str,
    user_prompt: str,
    model: str,
    provider_label: str,
    metadata: dict[str, Any] | None,
    prompt_guard_applied: bool = False,
) -> None:
    if not is_llm_prompt_audit_enabled():
        return
    meta = dict(metadata or {})
    tid = str(llm_task_id).strip()
    if not tid:
        return
    try:
        row_id = uuid.UUID(tid)
    except ValueError:
        logger.warning("llm_task_id 非合法 UUID，跳过审计: %s", tid[:16])
        return

    sys_t = str(system_prompt or "")
    usr_t = str(user_prompt or "")
    trace_id = meta.get("trace_id")
    if trace_id is not None:
        trace_id = str(trace_id).strip() or None
    wf_run = _parse_uuid(meta.get("workflow_run_id"))
    wf_step = _parse_uuid(meta.get("workflow_step_id"))
    role_id = meta.get("role_id")
    role_id_s = str(role_id).strip() if role_id is not None else None
    step_key = meta.get("step_key")
    step_key_s = str(step_key).strip() if step_key is not None else None
    wf_type = meta.get("workflow_type") or meta.get("workflow")
    wf_type_s = str(wf_type).strip() if wf_type is not None else None

    row: dict[str, Any] = {
        "id": str(row_id),
        "trace_id": trace_id,
        "workflow_run_id": str(wf_run) if wf_run else None,
        "workflow_step_id": str(wf_step) if wf_step else None,
        "role_id": role_id_s,
        "step_key": step_key_s,
        "workflow_type": wf_type_s,
        "model": str(model or ""),
        "provider_label": str(provider_label or ""),
        "system_prompt": sys_t,
        "user_prompt": usr_t,
        "system_chars": len(sys_t),
        "user_chars": len(usr_t),
        "metadata_json": meta,
        "prompt_guard_applied": bool(prompt_guard_applied),
    }

    logger.info(
        "[LLM] llm_task_id=%s trace_id=%s workflow_run_id=%s role_id=%s step_key=%s "
        "model=%s sys_chars=%d user_chars=%d guard=%s",
        str(row_id),
        trace_id or "-",
        str(wf_run) if wf_run else "-",
        role_id_s or "-",
        step_key_s or "-",
        str(model or ""),
        len(sys_t),
        len(usr_t),
        prompt_guard_applied,
    )

    db_url = env_str("DATABASE_URL", "").strip()
    if not db_url:
        _append_jsonl(row)
        return
    try:
        engine = create_engine(db_url, poolclass=NullPool, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO llm_prompt_requests (
                        id, trace_id, workflow_run_id, workflow_step_id,
                        role_id, step_key, workflow_type, model, provider_label,
                        system_prompt, user_prompt, system_chars, user_chars,
                        metadata_json, prompt_guard_applied
                    ) VALUES (
                        :id, :trace_id, :workflow_run_id, :workflow_step_id,
                        :role_id, :step_key, :workflow_type, :model, :provider_label,
                        :system_prompt, :user_prompt, :system_chars, :user_chars,
                        CAST(:metadata_json AS jsonb), :prompt_guard_applied
                    )
                    """
                ),
                {
                    "id": row_id,
                    "trace_id": trace_id,
                    "workflow_run_id": wf_run,
                    "workflow_step_id": wf_step,
                    "role_id": role_id_s,
                    "step_key": step_key_s,
                    "workflow_type": wf_type_s,
                    "model": str(model or ""),
                    "provider_label": str(provider_label or ""),
                    "system_prompt": sys_t,
                    "user_prompt": usr_t,
                    "system_chars": len(sys_t),
                    "user_chars": len(usr_t),
                    "metadata_json": json.dumps(meta, ensure_ascii=False),
                    "prompt_guard_applied": bool(prompt_guard_applied),
                },
            )
            conn.commit()
    except Exception:
        logger.warning("llm prompt audit 入库失败，改写入 JSONL", exc_info=True)
        _append_jsonl(row)


def read_llm_prompt_audit_from_jsonl(llm_task_id: uuid.UUID) -> dict[str, Any] | None:
    """从兜底 JSONL 中按 id 读取最后一次匹配记录（与入库前 row 结构一致）。"""
    path = _jsonl_fallback_path()
    if not path.is_file():
        return None
    want = str(llm_task_id)
    found: dict[str, Any] | None = None
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if str(obj.get("id", "")) == want:
                    found = obj
    except OSError:
        return None
    return found


def normalize_llm_prompt_audit_row(d: dict[str, Any]) -> dict[str, Any]:
    """与 LlmPromptRequestRepository.get_by_id 返回字段对齐。"""
    out = dict(d)
    if "created_at" not in out:
        out["created_at"] = None
    for k in ("id", "workflow_run_id", "workflow_step_id"):
        v = out.get(k)
        if v is not None and not isinstance(v, str):
            out[k] = str(v)
    return out


def try_read_llm_prompt_audit_fallback(llm_task_id: uuid.UUID) -> dict[str, Any] | None:
    """管理员查询：DB 无行时是否允许读本地 JSONL（默认开启，便于未迁移/入库失败环境）。"""
    if not env_bool("WRITER_LLM_PROMPT_AUDIT_API_JSONL_FALLBACK", True):
        return None
    raw = read_llm_prompt_audit_from_jsonl(llm_task_id)
    if raw is None:
        return None
    return normalize_llm_prompt_audit_row(raw)
