from __future__ import annotations

from dataclasses import dataclass

from packages.core.config import env_bool, env_int, env_str


@dataclass(frozen=True)
class AuthRuntimeConfig:
    jwt_secret: str = "dev-insecure-jwt-secret-change-me"
    jwt_issuer: str = "writeragent"
    access_ttl_minutes: int = 15
    refresh_ttl_days: int = 30
    enforce_prod_secret: bool = True

    @classmethod
    def from_env(cls) -> "AuthRuntimeConfig":
        return cls(
            jwt_secret=env_str("WRITER_AUTH_JWT_SECRET", "dev-insecure-jwt-secret-change-me"),
            jwt_issuer=env_str("WRITER_AUTH_JWT_ISSUER", "writeragent"),
            access_ttl_minutes=env_int("WRITER_AUTH_ACCESS_TTL_MINUTES", 15, minimum=1, maximum=24 * 60),
            refresh_ttl_days=env_int("WRITER_AUTH_REFRESH_TTL_DAYS", 30, minimum=1, maximum=365),
            enforce_prod_secret=env_bool("WRITER_AUTH_ENFORCE_PROD_SECRET", True),
        )
