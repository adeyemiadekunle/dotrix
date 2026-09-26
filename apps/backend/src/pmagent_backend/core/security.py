"""Password hashing, access tokens, and opaque one-time tokens.

- Passwords: Argon2id (argon2-cffi defaults), rehashed on login when params change.
- Access tokens: short-lived HS256 JWTs carrying only the user ID.
- Refresh / email / reset tokens: random opaque strings; only their SHA-256
  hash is stored, so a database leak does not leak usable tokens.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from .errors import Unauthorized

_hasher = PasswordHasher()
# Verified against when the user doesn't exist, so login timing doesn't reveal
# which emails are registered.
_DUMMY_HASH = _hasher.hash("pmagent-timing-equalizer")

ACCESS_TOKEN_TYPE = "access"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def create_access_token(
    user_id: uuid.UUID, *, secret: str, issuer: str, ttl: timedelta
) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "type": ACCESS_TOKEN_TYPE,
        "iss": issuer,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


def decode_access_token(token: str, *, secret: str, issuer: str) -> uuid.UUID:
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            issuer=issuer,
            options={"require": ["sub", "exp", "iat", "iss"]},
        )
        if claims.get("type") != ACCESS_TOKEN_TYPE:
            raise Unauthorized("Invalid access token")
        return uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise Unauthorized("Invalid or expired access token") from exc


def generate_token() -> str:
    """Opaque token for refresh, email verification, and password reset."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
