from urllib.parse import parse_qs, urlparse

from httpx import AsyncClient

from pmagent_backend.core.email import OutboxEmailSender


def link_token(outbox: OutboxEmailSender, path: str) -> str:
    """Token from the newest emailed link to `path`."""
    for message in reversed(outbox.messages):
        for word in message.body.split():
            url = urlparse(word)
            if url.path == path:
                return parse_qs(url.query)["token"][0]
    raise AssertionError(f"no email with a {path} link")


# -- sign-up ------------------------------------------------------------------------


async def test_signup_logs_in_and_creates_personal_workspace(signup, db_client: AsyncClient) -> None:
    ada = await signup(email="Ada@Example.com")
    assert ada.email == "ada@example.com"  # normalised
    assert ada.user["email_verified"] is False

    me = await db_client.get("/v1/me", headers=ada.headers)
    assert me.status_code == 200
    assert me.json()["id"] == ada.id

    workspaces = (await db_client.get("/v1/workspaces", headers=ada.headers)).json()
    assert [(w["kind"], w["role"]) for w in workspaces] == [("personal", "owner")]


async def test_signup_sends_verification_email(signup, outbox: OutboxEmailSender) -> None:
    await signup()
    assert outbox.messages[-1].to == "ada@example.com"
    assert link_token(outbox, "/verify-email")


async def test_duplicate_email_is_rejected_case_insensitively(signup, db_client: AsyncClient) -> None:
    await signup(email="ada@example.com")
    res = await db_client.post(
        "/v1/auth/signup",
        json={"email": "ADA@example.com", "password": "another password", "display_name": "A"},
    )
    assert res.status_code == 409


async def test_signup_validates_input(db_client: AsyncClient) -> None:
    res = await db_client.post(
        "/v1/auth/signup", json={"email": "not-an-email", "password": "short", "display_name": ""}
    )
    assert res.status_code == 422
    fields = {tuple(e["loc"])[-1] for e in res.json()["errors"]}
    assert fields == {"email", "password", "display_name"}


# -- login and tokens ---------------------------------------------------------------


async def test_login(signup, db_client: AsyncClient) -> None:
    ada = await signup()
    res = await db_client.post(
        "/v1/auth/login", json={"email": "ADA@example.com", "password": ada.password}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == 15 * 60
    me = await db_client.get("/v1/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json()["email"] == "ada@example.com"


async def test_login_failures_look_the_same(signup, db_client: AsyncClient) -> None:
    await signup()
    wrong_password = await db_client.post(
        "/v1/auth/login", json={"email": "ada@example.com", "password": "wrong password"}
    )
    unknown_email = await db_client.post(
        "/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong password"}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["detail"] == unknown_email.json()["detail"]


async def test_protected_routes_need_a_valid_token(db_client: AsyncClient) -> None:
    assert (await db_client.get("/v1/me")).status_code == 401
    bad = await db_client.get("/v1/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert bad.status_code == 401


async def test_refresh_rotates_tokens(signup, db_client: AsyncClient) -> None:
    ada = await signup()
    res = await db_client.post(
        "/v1/auth/refresh", json={"refresh_token": ada.tokens["refresh_token"]}
    )
    assert res.status_code == 200
    rotated = res.json()
    assert rotated["refresh_token"] != ada.tokens["refresh_token"]

    again = await db_client.post(
        "/v1/auth/refresh", json={"refresh_token": rotated["refresh_token"]}
    )
    assert again.status_code == 200


async def test_refresh_token_reuse_revokes_the_session(signup, db_client: AsyncClient) -> None:
    ada = await signup()
    original = ada.tokens["refresh_token"]
    rotated = (await db_client.post("/v1/auth/refresh", json={"refresh_token": original})).json()

    # The old token comes back (stolen or replayed): rejected, and the family is revoked.
    replay = await db_client.post("/v1/auth/refresh", json={"refresh_token": original})
    assert replay.status_code == 401
    legit = await db_client.post(
        "/v1/auth/refresh", json={"refresh_token": rotated["refresh_token"]}
    )
    assert legit.status_code == 401


async def test_logout_revokes_refresh_token(signup, db_client: AsyncClient) -> None:
    ada = await signup()
    token = ada.tokens["refresh_token"]
    assert (await db_client.post("/v1/auth/logout", json={"refresh_token": token})).status_code == 204
    assert (await db_client.post("/v1/auth/refresh", json={"refresh_token": token})).status_code == 401


# -- email verification -------------------------------------------------------------


async def test_verify_email(signup, db_client: AsyncClient, outbox: OutboxEmailSender) -> None:
    ada = await signup()
    token = link_token(outbox, "/verify-email")

    assert (await db_client.post("/v1/auth/verify-email", json={"token": token})).status_code == 204
    me = (await db_client.get("/v1/me", headers=ada.headers)).json()
    assert me["email_verified"] is True

    reused = await db_client.post("/v1/auth/verify-email", json={"token": token})
    assert reused.status_code == 400
    assert reused.json()["type"].endswith("/invalid_link")


async def test_resend_invalidates_the_previous_link(
    signup, db_client: AsyncClient, outbox: OutboxEmailSender
) -> None:
    ada = await signup()
    first = link_token(outbox, "/verify-email")
    res = await db_client.post("/v1/auth/verify-email/resend", headers=ada.headers)
    assert res.status_code == 202
    second = link_token(outbox, "/verify-email")

    assert (await db_client.post("/v1/auth/verify-email", json={"token": first})).status_code == 400
    assert (await db_client.post("/v1/auth/verify-email", json={"token": second})).status_code == 204


# -- password reset -----------------------------------------------------------------


async def test_password_reset_for_unknown_email_reveals_nothing(
    db_client: AsyncClient, outbox: OutboxEmailSender
) -> None:
    res = await db_client.post("/v1/auth/password-reset/request", json={"email": "no@example.com"})
    assert res.status_code == 202
    assert outbox.messages == []


async def test_password_reset(signup, db_client: AsyncClient, outbox: OutboxEmailSender) -> None:
    ada = await signup()
    res = await db_client.post("/v1/auth/password-reset/request", json={"email": ada.email})
    assert res.status_code == 202
    token = link_token(outbox, "/reset-password")

    new_password = "a brand new passphrase"
    res = await db_client.post(
        "/v1/auth/password-reset/confirm", json={"token": token, "new_password": new_password}
    )
    assert res.status_code == 204

    old_login = await db_client.post(
        "/v1/auth/login", json={"email": ada.email, "password": ada.password}
    )
    assert old_login.status_code == 401
    new_login = await db_client.post(
        "/v1/auth/login", json={"email": ada.email, "password": new_password}
    )
    assert new_login.status_code == 200
    # Existing sessions are signed out.
    old_refresh = await db_client.post(
        "/v1/auth/refresh", json={"refresh_token": ada.tokens["refresh_token"]}
    )
    assert old_refresh.status_code == 401
    # Single use.
    again = await db_client.post(
        "/v1/auth/password-reset/confirm", json={"token": token, "new_password": new_password}
    )
    assert again.status_code == 400
