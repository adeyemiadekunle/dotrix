"""Magic-link sign-in: request a link by email, follow it once to get a session."""
from typing import Any

from httpx import AsyncClient

from pmagent_backend.core.email import OutboxEmailSender
from pmagent_backend.core.ratelimit import MemoryRateLimiter


async def test_sign_in_with_an_emailed_link(db_client: AsyncClient, signup, outbox: OutboxEmailSender, email_token) -> None:
    ada = await signup()
    outbox.messages.clear()
    res = await db_client.post("/v1/auth/magic-link/request", json={"email": "ADA@example.com"})
    assert res.status_code == 202
    [message] = outbox.messages
    assert message.to == "ada@example.com" and message.subject == "Your pmagent sign-in link"
    assert message.html and "Sign in" in message.html

    token = email_token("/magic-link")
    signed_in = await db_client.post("/v1/auth/magic-link/verify", json={"token": token})
    assert signed_in.status_code == 200
    session = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}
    me = (await db_client.get("/v1/me", headers=session)).json()
    assert me["id"] == ada.id and me["email_verified"] is True  # following the link proved the inbox
    # A link works once.
    again = await db_client.post("/v1/auth/magic-link/verify", json={"token": token})
    assert again.status_code == 400 and again.json()["type"].endswith("/invalid_link")


async def test_unknown_emails_look_the_same_and_get_nothing(db_client: AsyncClient, outbox: OutboxEmailSender) -> None:
    res = await db_client.post("/v1/auth/magic-link/request", json={"email": "nobody@example.com"})
    assert res.status_code == 202 and outbox.messages == []


async def test_only_the_newest_link_works(db_client: AsyncClient, signup, outbox: OutboxEmailSender, email_token) -> None:
    await signup()
    await db_client.post("/v1/auth/magic-link/request", json={"email": "ada@example.com"})
    first = email_token("/magic-link")
    await db_client.post("/v1/auth/magic-link/request", json={"email": "ada@example.com"})
    second = email_token("/magic-link")
    assert (await db_client.post("/v1/auth/magic-link/verify", json={"token": first})).status_code == 400
    assert (await db_client.post("/v1/auth/magic-link/verify", json={"token": second})).status_code == 200


async def test_other_links_dont_sign_you_in(db_client: AsyncClient, signup, email_token) -> None:
    await signup()  # sends a verification link
    verify = email_token("/verify-email")
    assert (await db_client.post("/v1/auth/magic-link/verify", json={"token": verify})).status_code == 400


async def test_requests_are_queued_and_rate_limited(db_client: AsyncClient, signup) -> None:
    await signup()
    app = db_client._transport.app  # type: ignore[attr-defined]
    app.state.rate_limiter = MemoryRateLimiter()
    queued: list[tuple[str, dict[str, Any]]] = []

    class Recorder:
        async def enqueue(self, name: str, **kwargs: Any) -> None:
            queued.append((name, kwargs))

    app.state.jobs = Recorder()
    for _ in range(5):
        assert (await db_client.post("/v1/auth/magic-link/request", json={"email": "ada@example.com"})).status_code == 202
    assert queued[0] == ("send_magic_link", {"email": "ada@example.com"})  # the lookup is in the job
    assert (await db_client.post("/v1/auth/magic-link/request", json={"email": "ada@example.com"})).status_code == 429
