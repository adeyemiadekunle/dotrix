import uuid
from datetime import timedelta

import jwt
import pytest

from dotrix_backend.core import security
from dotrix_backend.core.errors import Unauthorized

SECRET = "unit-test-secret-that-is-long-enough-to-use"


def test_password_hash_roundtrip() -> None:
    hashed = security.hash_password("correct horse battery")
    assert hashed.startswith("$argon2id$")
    assert security.verify_password(hashed, "correct horse battery")
    assert not security.verify_password(hashed, "wrong password")


def test_verify_without_hash_is_always_false() -> None:
    assert not security.verify_password(None, "anything")
    assert not security.verify_password("not-a-hash", "anything")


def test_access_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    token = security.create_access_token(
        user_id, secret=SECRET, issuer="dotrix", ttl=timedelta(minutes=5)
    )
    assert security.decode_access_token(token, secret=SECRET, issuer="dotrix") == user_id


@pytest.mark.parametrize(
    ("secret", "issuer", "ttl"),
    [
        ("a-different-secret-that-is-long-enough", "dotrix", timedelta(minutes=5)),
        (SECRET, "someone-else", timedelta(minutes=5)),
        (SECRET, "dotrix", timedelta(seconds=-1)),  # expired
    ],
)
def test_access_token_rejected(secret: str, issuer: str, ttl: timedelta) -> None:
    token = security.create_access_token(uuid.uuid4(), secret=secret, issuer=issuer, ttl=ttl)
    with pytest.raises(Unauthorized):
        security.decode_access_token(token, secret=SECRET, issuer="dotrix")


def test_token_of_another_type_rejected() -> None:
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "refresh", "iss": "dotrix", "iat": 0, "exp": 2**40},
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(Unauthorized):
        security.decode_access_token(token, secret=SECRET, issuer="dotrix")


def test_opaque_tokens_are_random_and_hashed() -> None:
    a, b = security.generate_token(), security.generate_token()
    assert a != b and len(a) >= 40
    assert security.hash_token(a) == security.hash_token(a)
    assert len(security.hash_token(a)) == 64
