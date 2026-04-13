from __future__ import annotations

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.foreshadowing import Foreshadowing


class ForeshadowingRepository(BaseRepository):
    def create(
        self,
        *,
        project_id,
        setup_chapter_no: int | None = None,
        setup_text: str | None = None,
        expected_payoff: str | None = None,
        payoff_chapter_no: int | None = None,
        payoff_text: str | None = None,
        status: str = "open",
        auto_commit: bool = True,
    ) -> Foreshadowing:
        row = Foreshadowing(
            project_id=project_id,
            setup_chapter_no=setup_chapter_no,
            setup_text=setup_text,
            expected_payoff=expected_payoff,
            payoff_chapter_no=payoff_chapter_no,
            payoff_text=payoff_text,
            status=status,
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def get(self, foreshadowing_id) -> Foreshadowing | None:
        return self.db.get(Foreshadowing, foreshadowing_id)

    def list_by_project(
        self,
        *,
        project_id,
        limit: int = 300,
        status: str | None = None,
    ) -> list[Foreshadowing]:
        stmt = select(Foreshadowing).where(Foreshadowing.project_id == project_id)
        if status is not None:
            stmt = stmt.where(Foreshadowing.status == status)
        stmt = stmt.order_by(Foreshadowing.updated_at.desc()).limit(max(1, int(limit)))
        return list(self.db.execute(stmt).scalars().all())

    def update(self, foreshadowing_id, *, auto_commit: bool = True, **fields) -> Foreshadowing | None:
        row = self.get(foreshadowing_id)
        if row is None:
            return None
        allowed = {
            "setup_chapter_no",
            "setup_text",
            "expected_payoff",
            "payoff_chapter_no",
            "payoff_text",
            "status",
        }
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            setattr(row, key, value)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def delete(self, foreshadowing_id, *, auto_commit: bool = True) -> bool:
        row = self.get(foreshadowing_id)
        if row is None:
            return False
        self.db.delete(row)
        if auto_commit:
            self.db.commit()
        else:
            self.db.flush()
        return True

