from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import and_, select

from .base import BaseRepository
from packages.storage.postgres.models.retrieval_eval_daily_stat import RetrievalEvalDailyStat
from packages.storage.postgres.models.retrieval_eval_event import RetrievalEvalEvent


@dataclass(frozen=True)
class RetrievalDailyStatSnapshot:
    project_id: str
    stat_date: str
    variant: str
    impressions: int
    clicks: int
    ctr: float


class RetrievalEvalRepository(BaseRepository):
    """在线评测仓储：事件明细 + 日聚合。"""

    def create_impression(
        self,
        *,
        project_id,
        request_id: str,
        user_id: str | None,
        query: str,
        variant: str,
        rerank_backend: str | None,
        impressed_doc_ids: list[str],
        context_json: dict | None = None,
    ) -> RetrievalEvalEvent:
        event = self._get_by_request(project_id=project_id, request_id=request_id)
        if event is not None:
            event.user_id = user_id
            event.query = query
            event.variant = variant
            event.rerank_backend = rerank_backend
            event.impressed_doc_ids = list(impressed_doc_ids)
            event.context_json = context_json or {}
            self.db.commit()
            self.db.refresh(event)
            return event

        event = RetrievalEvalEvent(
            project_id=project_id,
            request_id=request_id,
            user_id=user_id,
            query=query,
            variant=variant,
            rerank_backend=rerank_backend,
            impressed_doc_ids=list(impressed_doc_ids),
            clicked=False,
            context_json=context_json or {},
        )
        self.db.add(event)
        self.db.flush()

        self._upsert_daily(
            project_id=project_id,
            stat_date=event.created_at.date(),
            variant=variant,
            impressions_delta=1,
            clicks_delta=0,
        )

        self.db.commit()
        self.db.refresh(event)
        return event

    def record_feedback(
        self,
        *,
        project_id,
        request_id: str,
        user_id: str | None,
        clicked_doc_id: str | None,
        clicked: bool = True,
    ) -> bool:
        event = self._get_by_request(project_id=project_id, request_id=request_id)
        if event is None:
            return False
        if user_id is not None and event.user_id not in {None, user_id}:
            return False

        need_daily_click_delta = 0
        if clicked and not bool(event.clicked):
            need_daily_click_delta = 1
        event.clicked = bool(clicked)
        event.clicked_doc_id = clicked_doc_id if clicked else None

        if need_daily_click_delta:
            self._upsert_daily(
                project_id=project_id,
                stat_date=event.created_at.date(),
                variant=event.variant,
                impressions_delta=0,
                clicks_delta=need_daily_click_delta,
            )

        self.db.commit()
        return True

    def get_daily_stats(
        self,
        *,
        project_id,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[RetrievalDailyStatSnapshot]:
        stmt = select(RetrievalEvalDailyStat).where(
            RetrievalEvalDailyStat.project_id == project_id
        )
        if start_date is not None:
            stmt = stmt.where(RetrievalEvalDailyStat.stat_date >= start_date)
        if end_date is not None:
            stmt = stmt.where(RetrievalEvalDailyStat.stat_date <= end_date)
        stmt = stmt.order_by(
            RetrievalEvalDailyStat.stat_date.asc(),
            RetrievalEvalDailyStat.variant.asc(),
        )

        out: list[RetrievalDailyStatSnapshot] = []
        for row in self.db.execute(stmt).scalars().all():
            out.append(
                RetrievalDailyStatSnapshot(
                    project_id=str(row.project_id),
                    stat_date=row.stat_date.isoformat(),
                    variant=str(row.variant),
                    impressions=int(row.impressions),
                    clicks=int(row.clicks),
                    ctr=float(row.ctr),
                )
            )
        return out

    def _get_by_request(self, *, project_id, request_id: str) -> RetrievalEvalEvent | None:
        stmt = select(RetrievalEvalEvent).where(
            and_(
                RetrievalEvalEvent.project_id == project_id,
                RetrievalEvalEvent.request_id == request_id,
            )
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def _upsert_daily(
        self,
        *,
        project_id,
        stat_date: date,
        variant: str,
        impressions_delta: int,
        clicks_delta: int,
    ) -> None:
        stmt = select(RetrievalEvalDailyStat).where(
            RetrievalEvalDailyStat.project_id == project_id,
            RetrievalEvalDailyStat.stat_date == stat_date,
            RetrievalEvalDailyStat.variant == variant,
        )
        row = self.db.execute(stmt).scalar_one_or_none()
        if row is None:
            row = RetrievalEvalDailyStat(
                project_id=project_id,
                stat_date=stat_date,
                variant=variant,
                impressions=0,
                clicks=0,
                ctr=0.0,
            )
            self.db.add(row)
            self.db.flush()

        row.impressions = int(row.impressions) + int(impressions_delta)
        row.clicks = int(row.clicks) + int(clicks_delta)
        row.ctr = float(row.clicks / row.impressions) if row.impressions > 0 else 0.0

