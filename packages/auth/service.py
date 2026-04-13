from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from packages.auth.passwords import hash_password, verify_password
from packages.auth.runtime_config import AuthRuntimeConfig
from packages.auth.token import (
    decode_jwt,
    issue_access_token,
    issue_refresh_token,
    token_sha256,
)
from packages.storage.postgres.repositories.auth_refresh_token_repository import (
    AuthRefreshTokenRepository,
)
from packages.storage.postgres.repositories.user_repository import UserRepository


class AuthError(RuntimeError):
    pass


class AuthService:
    def __init__(
        self,
        *,
        user_repo: UserRepository,
        refresh_repo: AuthRefreshTokenRepository,
        config: AuthRuntimeConfig,
    ) -> None:
        self.user_repo = user_repo
        self.refresh_repo = refresh_repo
        self.config = config

    def register(self, *, username: str, email: str | None, password: str, preferences: dict | None = None) -> dict[str, Any]:
        if self.user_repo.get_by_username(username) is not None:
            raise AuthError("username 已存在")
        pwd_hash = hash_password(password)
        user = self.user_repo.create(
            username=username,
            email=email,
            password_hash=pwd_hash,
            preferences=preferences or {},
        )
        return self._issue_tokens_for_user(user, ip_hash=None, user_agent=None)

    def login(
        self,
        *,
        username: str,
        password: str,
        ip_hash: str | None,
        user_agent: str | None,
    ) -> dict[str, Any]:
        user = self.user_repo.get_by_username(username)
        if user is None:
            raise AuthError("用户名或密码错误")
        if not verify_password(password, user.password_hash):
            raise AuthError("用户名或密码错误")
        return self._issue_tokens_for_user(user, ip_hash=ip_hash, user_agent=user_agent)

    def refresh(
        self,
        *,
        refresh_token: str,
        ip_hash: str | None,
        user_agent: str | None,
    ) -> dict[str, Any]:
        claims = decode_jwt(refresh_token, self.config.jwt_secret)
        if claims.get("typ") != "refresh":
            raise AuthError("refresh token 类型非法")

        jti = str(claims.get("jti") or "").strip()
        if not jti:
            raise AuthError("refresh token 缺少 jti")

        record = self.refresh_repo.get_active_by_jti(jti)
        if record is None:
            raise AuthError("refresh token 已失效")
        if not hmac_compare(token_sha256(refresh_token), str(record.token_hash)):
            raise AuthError("refresh token 校验失败")

        user = self.user_repo.get(record.user_id)
        if user is None:
            raise AuthError("用户不存在")

        self.refresh_repo.revoke_jti(jti)
        return self._issue_tokens_for_user(user, ip_hash=ip_hash, user_agent=user_agent)

    def logout(self, *, refresh_token: str | None = None) -> None:
        if not refresh_token:
            return
        try:
            claims = decode_jwt(refresh_token, self.config.jwt_secret)
        except Exception:
            return
        if claims.get("typ") != "refresh":
            return
        jti = str(claims.get("jti") or "").strip()
        if jti:
            self.refresh_repo.revoke_jti(jti)

    def authenticate_access_token(self, token: str) -> dict[str, Any]:
        claims = decode_jwt(token, self.config.jwt_secret)
        if claims.get("typ") != "access":
            raise AuthError("access token 类型非法")

        user_id_raw = claims.get("sub")
        if not user_id_raw:
            raise AuthError("access token 缺少 sub")

        try:
            user_id = UUID(str(user_id_raw))
        except ValueError as exc:
            raise AuthError("access token sub 非法") from exc

        user = self.user_repo.get(user_id)
        if user is None:
            raise AuthError("用户不存在")

        return {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "preferences": dict(user.preferences or {}),
            "claims": claims,
        }

    def _issue_tokens_for_user(self, user, *, ip_hash: str | None, user_agent: str | None) -> dict[str, Any]:
        access_token = issue_access_token(
            user_id=str(user.id),
            username=str(user.username),
            secret=self.config.jwt_secret,
            issuer=self.config.jwt_issuer,
            ttl_minutes=self.config.access_ttl_minutes,
        )
        refresh_token, jti, exp_dt = issue_refresh_token(
            user_id=str(user.id),
            username=str(user.username),
            secret=self.config.jwt_secret,
            issuer=self.config.jwt_issuer,
            ttl_days=self.config.refresh_ttl_days,
        )

        self.refresh_repo.create(
            jti=jti,
            user_id=user.id,
            token_hash=token_sha256(refresh_token),
            expires_at=exp_dt,
            ip_hash=ip_hash,
            user_agent=user_agent,
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": int(self.config.access_ttl_minutes * 60),
            "refresh_expires_at": exp_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "user": {
                "id": str(user.id),
                "username": user.username,
                "email": user.email,
                "preferences": dict(user.preferences or {}),
            },
        }


def hmac_compare(a: str, b: str) -> bool:
    from hmac import compare_digest

    return compare_digest(str(a), str(b))
