"""Magic-link sign-in: request a link by email, follow it once to get a session."""
from typing import Any

from httpx import AsyncClient

from dotrix_backend.core.email import OutboxEmailSender
from dotrix_backend.core.ratelimit import MemoryRateLimiter


async def test_sign_in_with_an_emailed_link(db_client: AsyncClient, signup, outbox: OutboxEmailSender, email_token) -> None:
    ada = await signup()
    outbox.messages.clear()
    res = await db_client.post("/v1/auth/magic-link/request", json={"email": "ADA@example.com"})
    assert res.status_code == 202
    [message] = outbox.messages
    assert message.to == "ada@example.com" and message.subject == "Your dotrix sign-in link"
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


async def test_a_new_address_gets_a_link_to_create_its_account(
    db_client: AsyncClient, outbox: OutboxEmailSender, email_token
) -> None:
    res = await db_client.post("/v1/auth/magic-link/request", json={"email": "Grace@Example.com"})
    assert res.status_code == 202  # the same answer as for an existing account
    [message] = outbox.messages
    assert message.to == "grace@example.com" and message.subject == "Finish creating your dotrix account"
    token = email_token("/signup/finish")

    # The page can show which address it's for, without using the link up.
    lookup = await db_client.post("/v1/auth/magic-link/signup/lookup", json={"token": token})
    assert lookup.status_code == 200 and lookup.json() == {"email": "grace@example.com"}

    created = await db_client.post("/v1/auth/magic-link/signup", json={"token": token, "display_name": "Grace"})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["user"]["email"] == "grace@example.com" and body["user"]["display_name"] == "Grace"
    assert body["user"]["email_verified"] is True  # the link proved the inbox; no verification email
    assert len(outbox.messages) == 1
    session = {"Authorization": f"Bearer {body['tokens']['access_token']}"}
    workspaces = (await db_client.get("/v1/workspaces", headers=session)).json()
    assert [w["kind"] for w in workspaces] == ["personal"]
    # No password: password login fails, but the next link signs in.
    login = await db_client.post("/v1/auth/login", json={"email": "grace@example.com", "password": "anything at all"})
    assert login.status_code == 401
    await db_client.post("/v1/auth/magic-link/request", json={"email": "grace@example.com"})
    assert outbox.messages[-1].subject == "Your dotrix sign-in link"
    # The sign-up link works once.
    again = await db_client.post("/v1/auth/magic-link/signup", json={"token": token, "display_name": "Grace"})
    assert again.status_code == 400
    assert (await db_client.post("/v1/auth/magic-link/signup/lookup", json={"token": token})).status_code == 400


async def test_only_the_newest_sign_up_link_works(db_client: AsyncClient, email_token) -> None:
    await db_client.post("/v1/auth/magic-link/request", json={"email": "grace@example.com"})
    first = email_token("/signup/finish")
    await db_client.post("/v1/auth/magic-link/request", json={"email": "grace@example.com"})
    second = email_token("/signup/finish")
    assert (await db_client.post("/v1/auth/magic-link/signup", json={"token": first, "display_name": "G"})).status_code == 400
    assert (await db_client.post("/v1/auth/magic-link/signup", json={"token": second, "display_name": "G"})).status_code == 201


async def test_a_sign_up_link_for_an_address_that_got_an_account_meanwhile(
    db_client: AsyncClient, signup, email_token
) -> None:
    await db_client.post("/v1/auth/magic-link/request", json={"email": "grace@example.com"})
    token = email_token("/signup/finish")
    await signup(email="grace@example.com", name="Grace")  # signed up with a password in the meantime
    res = await db_client.post("/v1/auth/magic-link/signup", json={"token": token, "display_name": "Grace 2"})
    assert res.status_code == 409 and "sign in instead" in res.json()["detail"]


async def test_sign_up_needs_a_name(db_client: AsyncClient, email_token) -> None:
    await db_client.post("/v1/auth/magic-link/request", json={"email": "grace@example.com"})
    token = email_token("/signup/finish")
    res = await db_client.post("/v1/auth/magic-link/signup", json={"token": token, "display_name": "   "})
    assert res.status_code == 422


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
