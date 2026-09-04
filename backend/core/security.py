from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

from core.config import settings

_BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    """Hash a password using bcrypt with cost factor 12.

    bd:deps-2026-09 iter1 (CHRIS-05) — was ``passlib.context.CryptContext``;
    passlib 1.7.4's bcrypt backend probes ``bcrypt.__about__.__version__``
    to detect the installed bcrypt version — bcrypt 5.0.0 removed that
    submodule entirely, so passlib's version-detection fallback runs an
    internal self-test (``detect_wrap_bug``) with a >72-byte hardcoded
    probe string, which bcrypt 5's stricter length validation then rejects
    — the resulting "password cannot be longer than 72 bytes" error is
    misleading; it has nothing to do with the caller's actual password.
    Every single call failed, 100% reproducible (see 14-chris-review.md
    CHRIS-05). Live callers confirmed via repo-wide grep
    (``grep -rn hash_password backend tests``): ``scripts/create_user.py``
    (ops tool) + test fixtures (``backend/tests/conftest.py``,
    ``tests/api/conftest.py``) — so this is a fix, not a removal.
    ``verify_password`` was already removed with the password-login route
    (ADR-007) — nothing in this codebase reads ``password_hash`` back for
    comparison anymore, so only the one-way hash direction needs to work.
    """
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS))
    return hashed.decode("utf-8")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT access token. Returns None if invalid."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        if payload.get("type") != "access":
            return None
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
