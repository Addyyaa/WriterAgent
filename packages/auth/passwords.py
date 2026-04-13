from __future__ import annotations

import base64
import hashlib
import hmac
import os


def hash_password(password: str, *, iterations: int = 120_000) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return (
        f"pbkdf2_sha256${iterations}$"
        f"{base64.urlsafe_b64encode(salt).decode('ascii')}$"
        f"{base64.urlsafe_b64encode(digest).decode('ascii')}"
    )


def verify_password(password: str, encoded_hash: str | None) -> bool:
    if not encoded_hash:
        return False

    if not encoded_hash.startswith("pbkdf2_sha256$"):
        # 向后兼容：历史数据可能直接存储明文或其他 hash。
        return hmac.compare_digest(encoded_hash, password)

    parts = encoded_hash.split("$")
    if len(parts) != 4:
        return False
    _, iter_raw, salt_raw, digest_raw = parts

    try:
        iterations = int(iter_raw)
        salt = base64.urlsafe_b64decode(salt_raw.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_raw.encode("ascii"))
    except Exception:
        return False

    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)
