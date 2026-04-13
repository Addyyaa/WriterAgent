from __future__ import annotations

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.session import SessionModel
from packages.storage.postgres.models.session_message import SessionMessage


class SessionRepository(BaseRepository):
    def create_session(
        self,
        *,
        project_id,
        user_id=None,
        title: str | None = None,
        metadata_json: dict | None = None,
        auto_commit: bool = True,
    ) -> SessionModel:
        row = SessionModel(
            project_id=project_id,
            user_id=user_id,
            title=title,
            metadata_json=metadata_json or {},
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def get_session(self, session_id) -> SessionModel | None:
        return self.db.get(SessionModel, session_id)

    def list_sessions(self, *, project_id, limit: int = 100) -> list[SessionModel]:
        stmt = (
            select(SessionModel)
            .where(SessionModel.project_id == project_id)
            .order_by(SessionModel.updated_at.desc())
            .limit(max(1, int(limit)))
        )
        return list(self.db.execute(stmt).scalars().all())

    def update_session(
        self,
        session_id,
        *,
        title: str | None = None,
        summary: str | None = None,
        status: str | None = None,
        linked_workflow_run_id=None,
        metadata_json: dict | None = None,
        auto_commit: bool = True,
    ) -> SessionModel | None:
        row = self.get_session(session_id)
        if row is None:
            return None
        if title is not None:
            row.title = title
        if summary is not None:
            row.summary = summary
        if status is not None:
            row.status = status
        if linked_workflow_run_id is not None:
            row.linked_workflow_run_id = linked_workflow_run_id
        if metadata_json is not None:
            row.metadata_json = dict(metadata_json)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def add_message(
        self,
        *,
        session_id,
        project_id,
        role: str,
        content: str,
        user_id=None,
        token_count: int | None = None,
        metadata_json: dict | None = None,
        auto_commit: bool = True,
    ) -> SessionMessage:
        row = SessionMessage(
            session_id=session_id,
            project_id=project_id,
            user_id=user_id,
            role=role,
            content=content,
            token_count=token_count,
            metadata_json=metadata_json or {},
        )
        self.db.add(row)
        session_row = self.get_session(session_id)
        if session_row is not None:
            session_row.updated_at = row.created_at
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def list_messages(
        self,
        *,
        session_id,
        limit: int = 200,
        ascending: bool = True,
    ) -> list[SessionMessage]:
        stmt = select(SessionMessage).where(SessionMessage.session_id == session_id)
        if ascending:
            stmt = stmt.order_by(SessionMessage.created_at.asc())
        else:
            stmt = stmt.order_by(SessionMessage.created_at.desc())
        stmt = stmt.limit(max(1, int(limit)))
        return list(self.db.execute(stmt).scalars().all())
