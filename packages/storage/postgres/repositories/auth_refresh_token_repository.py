from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.auth_refresh_token import AuthRefreshToken


class AuthRefreshTokenRepository(BaseRepository):
    def create(
        self,
        *,
        jti: str,
        user_id,
        token_hash: str,
        expires_at,
        ip_hash: str | None = None,
        user_agent: str | None = None,
        auto_commit: bool = True,
    ) -> AuthRefreshToken:
        row = AuthRefreshToken(
            jti=jti,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            ip_hash=ip_hash,
            user_agent=user_agent,
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def get_by_jti(self, jti: str) -> AuthRefreshToken | None:
        stmt = select(AuthRefreshToken).where(AuthRefreshToken.jti == jti)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_active_by_jti(self, jti: str) -> AuthRefreshToken | None:
        now = datetime.now(tz=timezone.utc)
        stmt = select(AuthRefreshToken).where(
            AuthRefreshToken.jti == jti,
            AuthRefreshToken.revoked_at.is_(None),
            AuthRefreshToken.expires_at > now,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def revoke_jti(self, jti: str, *, auto_commit: bool = True) -> bool:
        row = self.get_by_jti(jti)
        if row is None:
            return False
        if row.revoked_at is None:
            row.revoked_at = datetime.now(tz=timezone.utc)
            if auto_commit:
                self.db.commit()
            else:
                self.db.flush()
        return True

    def revoke_user(self, user_id, *, auto_commit: bool = True) -> int:
        now = datetime.now(tz=timezone.utc)
        stmt = select(AuthRefreshToken).where(
            AuthRefreshToken.user_id == user_id,
            AuthRefreshToken.revoked_at.is_(None),
        )
        rows = list(self.db.execute(stmt).scalars().all())
        for row in rows:
            row.revoked_at = now
        if rows:
            if auto_commit:
                self.db.commit()
            else:
                self.db.flush()
        return len(rows)

    def prune_expired(self, *, auto_commit: bool = True) -> int:
        now = datetime.now(tz=timezone.utc)
        stmt = select(AuthRefreshToken).where(AuthRefreshToken.expires_at <= now)
        rows = list(self.db.execute(stmt).scalars().all())
        count = 0
        for row in rows:
            self.db.delete(row)
            count += 1
        if count:
            if auto_commit:
                self.db.commit()
            else:
                self.db.flush()
        return count
