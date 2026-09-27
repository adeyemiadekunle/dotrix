"""Rate limits on sign-up, login, password reset, and verification emails (per IP and per
email), and password-reset requests doing their work in a background job."""
from typing import Any

import pytest
from httpx import AsyncClient

from pmagent_backend.core.email import OutboxEmailSender
from pmagent_backend.core.ratelimit import MemoryRateLimiter


@pytest.fixture
def rate_limited(db_client: AsyncClient) -> MemoryRateLimiter:
    limiter = MemoryRateLimiter()
    db_client._transport.app.state.rate_limiter = limiter  # type: ignore[attr-defined]
    return limiter


async def _login(client: AsyncClient, email: str, ip: str | None = None) -> Any:
    headers = {"X-Forwarded-For": ip} if ip else {}
    return await client.post("/v1/auth/login", json={"email": email, "password": "wrong password!"}, headers=headers)


async def test_login_is_limited_per_email(db_client: AsyncClient, rate_limited, signup) -> None:
    ada = await signup()
    for _ in range(10):
        assert (await _login(db_client, ada.email)).status_code == 401
    blocked = await _login(db_client, ada.email)
    assert blocked.status_code == 429
    assert blocked.headers["content-type"] == "application/problem+json"
    assert blocked.json()["type"].endswith("/rate_limited")
    assert blocked.json()["detail"].startswith("Too many attempts. Try again in")
    assert 1 <= int(blocked.headers["retry-after"]) <= 900
    # Even the right password waits: the limit is on attempts, not failures.
    right = await db_client.post("/v1/auth/login", json={"email": ada.email, "password": ada.password})
    assert right.status_code == 429
    # Other accounts are unaffected (from other machines).
    assert (await _login(db_client, "bob@example.com", ip="198.51.100.2")).status_code == 401


async def test_login_is_limited_per_ip(db_client: AsyncClient, rate_limited) -> None:
    # The test client's peer is 127.0.0.1, a trusted proxy: its X-Forwarded-For names the client.
    for n in range(50):
        assert (await _login(db_client, f"user{n}@example.com", ip="203.0.113.5")).status_code == 401
    assert (await _login(db_client, "another@example.com", ip="203.0.113.5")).status_code == 429
    assert (await _login(db_client, "another@example.com", ip="203.0.113.6")).status_code == 401


async def test_password_reset_requests_are_limited_and_run_in_the_background(
    db_client: AsyncClient, rate_limited, signup, outbox: OutboxEmailSender
) -> None:
    ada = await signup()
    outbox.messages.clear()
    enqueued: list[tuple[str, dict[str, Any]]] = []

    class Recorder:
        async def enqueue(self, name: str, **kwargs: Any) -> None:
            enqueued.append((name, kwargs))

    app = db_client._transport.app  # type: ignore[attr-defined]
    inline, app.state.jobs = app.state.jobs, Recorder()
    for email in (ada.email, "nobody@example.com"):
        res = await db_client.post("/v1/auth/password-reset/request", json={"email": email})
        assert res.status_code == 202
    # The request only queued the work: same response, same (tiny) work, account or not.
    assert enqueued == [
        ("send_password_reset", {"email": ada.email}),
        ("send_password_reset", {"email": "nobody@example.com"}),
    ]
    assert outbox.messages == []

    app.state.jobs = inline
    for _ in range(4):
        assert (await db_client.post("/v1/auth/password-reset/request", json={"email": ada.email})).status_code == 202
    assert len(outbox.messages) == 4  # (the job ran inline this time)
    blocked = await db_client.post("/v1/auth/password-reset/request", json={"email": ada.email})
    assert blocked.status_code == 429


async def test_signup_and_verification_resend_are_limited(db_client: AsyncClient, rate_limited, signup) -> None:
    ada = await signup()
    for _ in range(5):
        assert (await db_client.post("/v1/auth/verify-email/resend", headers=ada.headers)).status_code == 202
    assert (await db_client.post("/v1/auth/verify-email/resend", headers=ada.headers)).status_code == 429

    for n in range(9):  # 10 per IP per hour, counting Ada's
        body = {"email": f"new{n}@example.com", "password": "correct horse battery", "display_name": "N"}
        assert (await db_client.post("/v1/auth/signup", json=body)).status_code == 201
    body = {"email": "one-more@example.com", "password": "correct horse battery", "display_name": "N"}
    assert (await db_client.post("/v1/auth/signup", json=body)).status_code == 429
