from __future__ import annotations

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.user import User


class UserRepository(BaseRepository):
    def create(
        self,
        *,
        username: str,
        email: str | None = None,
        password_hash: str | None = None,
        preferences: dict | None = None,
    ) -> User:
        row = User(
            username=username,
            email=email,
            password_hash=password_hash,
            preferences=preferences or {},
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get(self, user_id) -> User | None:
        return self.db.get(User, user_id)

    def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username).limit(1)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_all(self, *, limit: int = 200) -> list[User]:
        stmt = select(User).order_by(User.created_at.desc()).limit(max(1, int(limit)))
        return list(self.db.execute(stmt).scalars().all())

    def update(
        self,
        user_id,
        *,
        username: str | None = None,
        email: str | None = None,
        password_hash: str | None = None,
        preferences: dict | None = None,
        auto_commit: bool = True,
    ) -> User | None:
        row = self.get(user_id)
        if row is None:
            return None
        if username is not None:
            row.username = username
        if email is not None:
            row.email = email
        if password_hash is not None:
            row.password_hash = password_hash
        if preferences is not None:
            row.preferences = dict(preferences)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def update_preferences(self, user_id, preferences: dict, *, auto_commit: bool = True) -> User | None:
        row = self.get(user_id)
        if row is None:
            return None
        row.preferences = dict(preferences or {})
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row
