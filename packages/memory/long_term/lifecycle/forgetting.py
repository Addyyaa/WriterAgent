from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from packages.memory.long_term.observability import MemoryObservability
from packages.memory.long_term.runtime_config import MemoryRuntimeConfig
from packages.storage.postgres.models.memory_fact import MemoryFact
from packages.storage.postgres.repositories.memory_fact_repository import (
    MemoryFactRepository,
)
from packages.storage.postgres.repositories.memory_repository import (
    MemoryChunkRepository,
)


@dataclass(frozen=True)
class ForgettingDecision:
    fact_id: str
    current_stage: str
    target_stage: str
    should_apply: bool
    reason: str
    score: float
    age_days: int
    mention_count: int


@dataclass(frozen=True)
class ForgettingRunResult:
    scanned: int
    kept: int
    cooled: int
    suppressed: int
    archived: int
    deleted: int
    dry_run: bool
    decisions: list[ForgettingDecision]


class MemoryForgettingService:
    """
    记忆遗忘服务（优先软遗忘，支持可控硬删除）。

    策略：
    1. cooling：进入冷却期（仍可保留检索）。
    2. suppressed：降权隐藏（默认检索排除）。
    3. archived：归档隐藏（保留可恢复证据）。
    4. deleted：硬删除（慎用，仅低价值长尾）。
    """

    _STAGE_RANK = {
        "active": 0,
        "cooling": 1,
        "suppressed": 2,
        "archived": 3,
        "deleted": 4,
    }

    def __init__(
        self,
        memory_repo: MemoryChunkRepository,
        memory_fact_repo: MemoryFactRepository | None = None,
        runtime_config: MemoryRuntimeConfig | None = None,
        observability: MemoryObservability | None = None,
    ) -> None:
        self.memory_repo = memory_repo
        self.memory_fact_repo = memory_fact_repo or MemoryFactRepository(memory_repo.db)
        self.runtime_config = runtime_config or MemoryRuntimeConfig.from_env()
        self.observability = observability or MemoryObservability(
            logger_name=self.runtime_config.observability.logger_name,
            enable_logging=self.runtime_config.observability.enable_logging,
        )

    def run_once(
        self,
        *,
        project_id,
        limit: int | None = None,
        dry_run: bool = True,
        allow_hard_delete: bool = False,
    ) -> ForgettingRunResult:
        cfg = self.runtime_config.forgetting
        if not cfg.enable:
            return ForgettingRunResult(
                scanned=0,
                kept=0,
                cooled=0,
                suppressed=0,
                archived=0,
                deleted=0,
                dry_run=dry_run,
                decisions=[],
            )

        effective_limit = cfg.run_limit if limit is None else int(limit)
        candidates = self.memory_fact_repo.list_forgetting_candidates(
            project_id=project_id,
            limit=effective_limit,
        )

        decisions: list[ForgettingDecision] = []
        kept = 0
        cooled = 0
        suppressed = 0
        archived = 0
        deleted = 0

        now = datetime.now(tz=timezone.utc)
        for fact in candidates:
            decision = self._decide(
                fact=fact,
                now=now,
                allow_hard_delete=allow_hard_delete,
            )
            decisions.append(decision)

            if decision.target_stage == "active":
                kept += 1
                if not dry_run and decision.should_apply:
                    self._apply_stage(
                        project_id=project_id,
                        fact=fact,
                        decision=decision,
                        now=now,
                    )
                continue

            if decision.target_stage == "cooling":
                cooled += 1
            elif decision.target_stage == "suppressed":
                suppressed += 1
            elif decision.target_stage == "archived":
                archived += 1
            elif decision.target_stage == "deleted":
                deleted += 1

            if dry_run or not decision.should_apply:
                continue

            self._apply_stage(
                project_id=project_id,
                fact=fact,
                decision=decision,
                now=now,
            )

        self.observability.incr("forgetting.run.calls")
        self.observability.incr("forgetting.run.scanned", len(candidates))
        self.observability.incr("forgetting.run.kept", kept)
        self.observability.incr("forgetting.run.cooled", cooled)
        self.observability.incr("forgetting.run.suppressed", suppressed)
        self.observability.incr("forgetting.run.archived", archived)
        self.observability.incr("forgetting.run.deleted", deleted)
        self.observability.emit(
            "memory.forgetting.run",
            project_id=str(project_id),
            scanned=len(candidates),
            kept=kept,
            cooled=cooled,
            suppressed=suppressed,
            archived=archived,
            deleted=deleted,
            dry_run=dry_run,
            allow_hard_delete=allow_hard_delete,
        )

        return ForgettingRunResult(
            scanned=len(candidates),
            kept=kept,
            cooled=cooled,
            suppressed=suppressed,
            archived=archived,
            deleted=deleted,
            dry_run=dry_run,
            decisions=decisions,
        )

    def _decide(
        self,
        *,
        fact: MemoryFact,
        now: datetime,
        allow_hard_delete: bool,
    ) -> ForgettingDecision:
        cfg = self.runtime_config.forgetting
        metadata = dict(fact.metadata_json or {})
        current_stage = str(metadata.get("forgetting_stage") or "active")
        mention_count = int(fact.mention_count or 0)
        last_seen = fact.last_seen_at or fact.updated_at or fact.created_at
        age_days = max(0, int((now - last_seen).total_seconds() // 86400))
        score = self._score(age_days=age_days, mention_count=mention_count)

        if bool(metadata.get("pin_memory")) or bool(metadata.get("legal_hold")):
            return ForgettingDecision(
                fact_id=str(fact.id),
                current_stage=current_stage,
                target_stage="active",
                should_apply=(current_stage != "active"),
                reason="protected",
                score=score,
                age_days=age_days,
                mention_count=mention_count,
            )

        if age_days < cfg.cooling_days:
            target = "active"
            reason = "recent"
        elif allow_hard_delete and age_days >= cfg.delete_days and mention_count <= cfg.min_mentions_to_keep:
            target = "deleted"
            reason = "old_and_low_signal"
        elif age_days >= cfg.archive_days:
            target = "archived"
            reason = "long_tail"
        elif age_days >= cfg.suppress_days:
            target = "suppressed"
            reason = "low_priority"
        else:
            target = "cooling"
            reason = "cooling_window"

        if target == "active":
            return ForgettingDecision(
                fact_id=str(fact.id),
                current_stage=current_stage,
                target_stage="active",
                should_apply=(current_stage != "active"),
                reason=reason,
                score=score,
                age_days=age_days,
                mention_count=mention_count,
            )

        current_rank = self._STAGE_RANK.get(current_stage, 0)
        target_rank = self._STAGE_RANK.get(target, 0)
        effective_target = target if target_rank >= current_rank else current_stage
        should_apply = effective_target != current_stage and effective_target != "active"

        return ForgettingDecision(
            fact_id=str(fact.id),
            current_stage=current_stage,
            target_stage=effective_target,
            should_apply=should_apply,
            reason=reason,
            score=score,
            age_days=age_days,
            mention_count=mention_count,
        )

    def _apply_stage(
        self,
        *,
        project_id,
        fact: MemoryFact,
        decision: ForgettingDecision,
        now: datetime,
    ) -> None:
        if decision.target_stage == "active":
            self.memory_fact_repo.clear_forgetting_stage(
                fact_id=fact.id,
                auto_commit=False,
            )
            linked_rows = self.memory_repo.list_by_source(
                project_id=project_id,
                source_type="memory_fact",
                source_id=fact.id,
                limit=1000,
            )
            for row in linked_rows:
                metadata = dict(row.metadata_json or {})
                for key in (
                    "forgetting_stage",
                    "forgetting_reason",
                    "forgetting_score",
                    "forgotten_at",
                ):
                    metadata.pop(key, None)
                self.memory_repo.update_chunk(
                    row.id,
                    metadata_json=metadata,
                    auto_commit=False,
                )
            self.memory_repo.db.commit()
            return

        if decision.target_stage == "deleted":
            self.memory_repo.delete_by_source(
                project_id=project_id,
                source_type="memory_fact",
                source_id=fact.id,
                auto_commit=False,
            )
            self.memory_fact_repo.delete_fact(fact.id, auto_commit=False)
            self.memory_repo.db.commit()
            return

        self.memory_fact_repo.mark_forgetting_stage(
            fact_id=fact.id,
            stage=decision.target_stage,
            reason=decision.reason,
            score=decision.score,
            now=now,
            auto_commit=False,
        )

        linked_rows = self.memory_repo.list_by_source(
            project_id=project_id,
            source_type="memory_fact",
            source_id=fact.id,
            limit=1000,
        )
        for row in linked_rows:
            metadata = dict(row.metadata_json or {})
            metadata.update(
                {
                    "forgetting_stage": decision.target_stage,
                    "forgetting_reason": decision.reason,
                    "forgetting_score": decision.score,
                    "forgotten_at": now.isoformat().replace("+00:00", "Z"),
                }
            )
            self.memory_repo.update_chunk(
                row.id,
                metadata_json=metadata,
                auto_commit=False,
            )

        self.memory_repo.db.commit()

    @staticmethod
    def _score(*, age_days: int, mention_count: int) -> float:
        freq_factor = 1.0 / (1.0 + math.log1p(max(0, mention_count)))
        age_factor = min(3.0, age_days / 30.0)
        return round(age_factor * freq_factor, 4)
