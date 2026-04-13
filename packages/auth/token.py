from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def _sign(message: bytes, secret: str) -> str:
    signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return _b64url_encode(signature)


def encode_jwt(payload: dict[str, Any], secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    message = f"{header_b64}.{payload_b64}".encode("utf-8")
    signature_b64 = _sign(message, secret)
    return f"{header_b64}.{payload_b64}.{signature_b64}"


def decode_jwt(token: str, secret: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("token 格式非法")

    header_b64, payload_b64, sig_b64 = parts
    message = f"{header_b64}.{payload_b64}".encode("utf-8")
    expected_sig = _sign(message, secret)

    if not hmac.compare_digest(sig_b64, expected_sig):
        raise ValueError("token 签名校验失败")

    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception as exc:
        raise ValueError("token 载荷非法") from exc

    exp = payload.get("exp")
    if exp is None:
        raise ValueError("token 缺少 exp")
    if float(exp) < datetime.now(tz=timezone.utc).timestamp():
        raise ValueError("token 已过期")

    return dict(payload)


def issue_access_token(
    *,
    user_id: str,
    username: str,
    secret: str,
    issuer: str,
    ttl_minutes: int,
) -> str:
    now = datetime.now(tz=timezone.utc)
    payload = {
        "iss": issuer,
        "sub": user_id,
        "username": username,
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=max(1, int(ttl_minutes)))).timestamp()),
    }
    return encode_jwt(payload, secret)


def issue_refresh_token(
    *,
    user_id: str,
    username: str,
    secret: str,
    issuer: str,
    ttl_days: int,
) -> tuple[str, str, datetime]:
    now = datetime.now(tz=timezone.utc)
    exp_dt = now + timedelta(days=max(1, int(ttl_days)))
    jti = str(uuid4())
    payload = {
        "iss": issuer,
        "sub": user_id,
        "username": username,
        "typ": "refresh",
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(exp_dt.timestamp()),
    }
    return encode_jwt(payload, secret), jti, exp_dt


def token_sha256(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
