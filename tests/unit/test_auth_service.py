from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from packages.auth.runtime_config import AuthRuntimeConfig
from packages.auth.service import AuthError, AuthService
from packages.auth.token import decode_jwt


@dataclass
class _User:
    id: UUID
    username: str
    email: str | None
    password_hash: str | None
    preferences: dict


@dataclass
class _RefreshRecord:
    jti: str
    user_id: UUID
    token_hash: str
    expires_at: datetime
    revoked_at: datetime | None = None


class _UserRepo:
    def __init__(self) -> None:
        self._by_id: dict[UUID, _User] = {}
        self._by_username: dict[str, _User] = {}

    def get_by_username(self, username: str) -> _User | None:
        return self._by_username.get(username)

    def create(self, *, username: str, email: str | None, password_hash: str, preferences: dict) -> _User:
        user = _User(
            id=uuid4(),
            username=username,
            email=email,
            password_hash=password_hash,
            preferences=dict(preferences or {}),
        )
        self._by_id[user.id] = user
        self._by_username[user.username] = user
        return user

    def get(self, user_id: UUID) -> _User | None:
        return self._by_id.get(user_id)


class _RefreshRepo:
    def __init__(self) -> None:
        self._records: dict[str, _RefreshRecord] = {}

    def create(
        self,
        *,
        jti: str,
        user_id,
        token_hash: str,
        expires_at,
        ip_hash,
        user_agent,
    ) -> _RefreshRecord:
        record = _RefreshRecord(
            jti=jti,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self._records[jti] = record
        return record

    def get_active_by_jti(self, jti: str) -> _RefreshRecord | None:
        row = self._records.get(jti)
        if row is None:
            return None
        if row.revoked_at is not None:
            return None
        if row.expires_at <= datetime.now(tz=timezone.utc):
            return None
        return row

    def revoke_jti(self, jti: str) -> None:
        row = self._records.get(jti)
        if row is None:
            return
        row.revoked_at = datetime.now(tz=timezone.utc)


class TestAuthService(unittest.TestCase):
    def setUp(self) -> None:
        self.user_repo = _UserRepo()
        self.refresh_repo = _RefreshRepo()
        self.cfg = AuthRuntimeConfig(
            jwt_secret="unit-test-secret",
            jwt_issuer="writeragent-test",
            access_ttl_minutes=15,
            refresh_ttl_days=30,
            enforce_prod_secret=False,
        )
        self.service = AuthService(
            user_repo=self.user_repo,
            refresh_repo=self.refresh_repo,
            config=self.cfg,
        )

    def test_register_and_authenticate_access_token(self) -> None:
        issued = self.service.register(
            username="alice",
            email="alice@example.com",
            password="pass-123456",
            preferences={"is_admin": True},
        )
        self.assertTrue(issued["access_token"])
        self.assertTrue(issued["refresh_token"])
        user = self.service.authenticate_access_token(issued["access_token"])
        self.assertEqual(user["username"], "alice")
        self.assertTrue(user["preferences"].get("is_admin"))

    def test_login_wrong_password_rejected(self) -> None:
        self.service.register(
            username="bob",
            email=None,
            password="pass-123456",
            preferences={},
        )
        with self.assertRaises(AuthError):
            self.service.login(
                username="bob",
                password="wrong-pass",
                ip_hash=None,
                user_agent=None,
            )

    def test_refresh_rotates_old_token(self) -> None:
        issued = self.service.register(
            username="carol",
            email=None,
            password="pass-123456",
            preferences={},
        )
        old_refresh = issued["refresh_token"]
        old_claims = decode_jwt(old_refresh, self.cfg.jwt_secret)
        old_jti = str(old_claims["jti"])

        rotated = self.service.refresh(
            refresh_token=old_refresh,
            ip_hash=None,
            user_agent=None,
        )
        self.assertNotEqual(rotated["refresh_token"], old_refresh)
        self.assertIsNone(self.refresh_repo.get_active_by_jti(old_jti))

        with self.assertRaises(AuthError):
            self.service.refresh(
                refresh_token=old_refresh,
                ip_hash=None,
                user_agent=None,
            )

    def test_logout_revokes_refresh_token(self) -> None:
        issued = self.service.register(
            username="dave",
            email=None,
            password="pass-123456",
            preferences={},
        )
        refresh = issued["refresh_token"]
        claims = decode_jwt(refresh, self.cfg.jwt_secret)
        jti = str(claims["jti"])
        self.assertIsNotNone(self.refresh_repo.get_active_by_jti(jti))

        self.service.logout(refresh_token=refresh)
        self.assertIsNone(self.refresh_repo.get_active_by_jti(jti))


if __name__ == "__main__":
    unittest.main(verbosity=2)
