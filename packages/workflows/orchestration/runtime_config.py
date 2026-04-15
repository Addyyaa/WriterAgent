from __future__ import annotations

import os
from dataclasses import dataclass

from packages.core.config import env_bool, env_float, env_int, env_str


@dataclass(frozen=True)
class OrchestratorRuntimeConfig:
    worker_poll_interval_seconds: float = 1.0
    worker_batch_size: int = 3
    max_step_seconds: int = 300
    worker_instance_id: str = "pid-0"
    run_initial_lease_seconds: int = 900
    run_lease_extend_seconds: int = 900
    recover_heartbeat_stale_seconds: int = 900
    enable_startup_lease_recover: bool = True
    default_max_retries: int = 2
    default_retry_delay_seconds: int = 30
    enable_auto_worker: bool = True
    agent_config_root: str = "apps/agents"
    schema_root: str = "packages/schemas"
    schema_strict: bool = True
    schema_degrade_mode: bool = False
    schema_consumption_strict: bool = False
    schema_consumption_degrade_mode: bool = False
    skill_config_root: str = "packages/skills"
    skill_runtime_fail_open: bool = True
    skill_runtime_strict_fail_close: bool = False
    skill_runtime_default_execution_mode: str = "active"
    skill_runtime_default_fallback_policy: str = "warn_only"
    skill_runtime_require_effect_trace: bool = True
    eval_online_enabled: bool = True
    eval_daily_cron: str = "0 2 * * *"
    retrieval_max_rounds: int = 20
    retrieval_round_top_k: int = 8
    retrieval_max_unique_evidence: int = 64
    retrieval_stop_min_coverage: float = 0.85
    retrieval_stop_min_gain: float = 0.05
    retrieval_stop_stale_rounds: int = 2
    workflow_run_timeout_seconds: int = 900
    context_chapter_window_before: int = 2
    context_chapter_window_after: int = 1
    api_v1_enabled: bool = False
    lifecycle_enabled: bool = False
    lifecycle_embedding_limit: int = 200
    lifecycle_rebuild_limit: int = 200
    lifecycle_forget_limit: int = 200
    lifecycle_forget_dry_run: bool = True
    review_expire_hours: int = 72
    webhook_enabled: bool = True
    webhook_batch_size: int = 50

    @classmethod
    def from_env(cls) -> "OrchestratorRuntimeConfig":
        wid = env_str("WRITER_WORKER_ID", "").strip() or f"pid-{os.getpid()}"
        return cls(
            worker_poll_interval_seconds=env_float("WRITER_ORCH_WORKER_POLL_INTERVAL", 1.0, minimum=0.1),
            worker_batch_size=env_int("WRITER_ORCH_WORKER_BATCH_SIZE", 3),
            max_step_seconds=env_int("WRITER_ORCH_MAX_STEP_SECONDS", 300),
            worker_instance_id=wid,
            run_initial_lease_seconds=env_int("WRITER_ORCH_RUN_INITIAL_LEASE_SECONDS", 900, minimum=60),
            run_lease_extend_seconds=env_int("WRITER_ORCH_RUN_LEASE_EXTEND_SECONDS", 900, minimum=60),
            recover_heartbeat_stale_seconds=env_int(
                "WRITER_ORCH_RECOVER_HEARTBEAT_STALE_SECONDS",
                900,
                minimum=60,
            ),
            enable_startup_lease_recover=env_bool("WRITER_ORCH_ENABLE_STARTUP_LEASE_RECOVER", True),
            default_max_retries=env_int("WRITER_ORCH_DEFAULT_MAX_RETRIES", 2),
            default_retry_delay_seconds=env_int("WRITER_ORCH_DEFAULT_RETRY_DELAY", 30),
            enable_auto_worker=env_bool("WRITER_ORCH_ENABLE_AUTO_WORKER", True),
            agent_config_root=env_str("WRITER_AGENT_CONFIG_ROOT", "apps/agents"),
            schema_root=env_str("WRITER_SCHEMA_ROOT", "packages/schemas"),
            schema_strict=env_bool("WRITER_SCHEMA_STRICT", True),
            schema_degrade_mode=env_bool("WRITER_SCHEMA_DEGRADE_MODE", False),
            schema_consumption_strict=env_bool("WRITER_SCHEMA_CONSUMPTION_STRICT", False),
            schema_consumption_degrade_mode=env_bool("WRITER_SCHEMA_CONSUMPTION_DEGRADE_MODE", False),
            skill_config_root=env_str("WRITER_SKILL_CONFIG_ROOT", "packages/skills"),
            skill_runtime_fail_open=env_bool("WRITER_SKILL_RUNTIME_FAIL_OPEN", True),
            skill_runtime_strict_fail_close=env_bool("WRITER_SKILL_RUNTIME_STRICT_FAIL_CLOSE", False),
            skill_runtime_default_execution_mode=env_str(
                "WRITER_SKILL_RUNTIME_DEFAULT_EXECUTION_MODE",
                "active",
            ),
            skill_runtime_default_fallback_policy=env_str(
                "WRITER_SKILL_RUNTIME_DEFAULT_FALLBACK_POLICY",
                "warn_only",
            ),
            skill_runtime_require_effect_trace=env_bool(
                "WRITER_SKILL_RUNTIME_REQUIRE_EFFECT_TRACE",
                True,
            ),
            eval_online_enabled=env_bool("WRITER_EVAL_ONLINE_ENABLED", True),
            eval_daily_cron=env_str("WRITER_EVAL_DAILY_CRON", "0 2 * * *"),
            retrieval_max_rounds=env_int("WRITER_RETRIEVAL_MAX_ROUNDS", 20),
            retrieval_round_top_k=env_int("WRITER_RETRIEVAL_ROUND_TOP_K", 8),
            retrieval_max_unique_evidence=env_int("WRITER_RETRIEVAL_MAX_UNIQUE_EVIDENCE", 64),
            retrieval_stop_min_coverage=env_float(
                "WRITER_RETRIEVAL_STOP_MIN_COVERAGE",
                0.85,
                minimum=0.0,
                maximum=1.0,
            ),
            retrieval_stop_min_gain=env_float(
                "WRITER_RETRIEVAL_STOP_MIN_GAIN",
                0.05,
                minimum=0.0,
                maximum=1.0,
            ),
            retrieval_stop_stale_rounds=env_int("WRITER_RETRIEVAL_STOP_STALE_ROUNDS", 2),
            workflow_run_timeout_seconds=env_int("WRITER_WORKFLOW_RUN_TIMEOUT_SECONDS", 900),
            context_chapter_window_before=env_int("WRITER_CONTEXT_CHAPTER_WINDOW_BEFORE", 2),
            context_chapter_window_after=env_int("WRITER_CONTEXT_CHAPTER_WINDOW_AFTER", 1),
            api_v1_enabled=env_bool("WRITER_API_V1_ENABLED", False),
            lifecycle_enabled=env_bool("WRITER_LIFECYCLE_ENABLED", False),
            lifecycle_embedding_limit=env_int("WRITER_LIFECYCLE_EMBEDDING_LIMIT", 200),
            lifecycle_rebuild_limit=env_int("WRITER_LIFECYCLE_REBUILD_LIMIT", 200),
            lifecycle_forget_limit=env_int("WRITER_LIFECYCLE_FORGET_LIMIT", 200),
            lifecycle_forget_dry_run=env_bool("WRITER_LIFECYCLE_FORGET_DRY_RUN", True),
            review_expire_hours=env_int("WRITER_REVIEW_EXPIRE_HOURS", 72, minimum=1, maximum=720),
            webhook_enabled=env_bool("WRITER_WEBHOOK_ENABLED", True),
            webhook_batch_size=env_int("WRITER_WEBHOOK_BATCH_SIZE", 50, minimum=1, maximum=500),
        )


@dataclass(frozen=True)
class PlannerRuntimeConfig:
    use_mock: bool = True
    fallback_to_mock_on_error: bool = True
    model: str = "mock-planner-v1"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    temperature: float = 0.2
    timeout_seconds: float = 20.0

    @classmethod
    def from_env(cls) -> "PlannerRuntimeConfig":
        return cls(
            use_mock=env_bool("WRITER_PLANNER_USE_MOCK", False),
            fallback_to_mock_on_error=env_bool("WRITER_PLANNER_FALLBACK_TO_MOCK", True),
            model=env_str("WRITER_PLANNER_MODEL", "mock-planner-v1"),
            base_url=env_str("WRITER_PLANNER_BASE_URL", "https://api.openai.com/v1"),
            api_key=env_str("WRITER_PLANNER_API_KEY", ""),
            temperature=env_float("WRITER_PLANNER_TEMPERATURE", 0.2, minimum=0.0, maximum=2.0),
            timeout_seconds=env_float("WRITER_PLANNER_TIMEOUT", 20.0, minimum=1.0, maximum=300.0),
        )
