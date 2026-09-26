from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.modules.api_tokens.models import ApiToken, DeviceAuthorization


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def make_token(client: AsyncClient, headers: dict[str, str], **body) -> dict:
    res = await client.post("/v1/me/tokens", json={"name": "script", **body}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


# -- API tokens -------------------------------------------------------------------------


async def test_create_use_list_and_revoke(signup, db_client: AsyncClient) -> None:
    ada = await signup()
    created = await make_token(db_client, ada.headers, name="laptop")
    token = created["token"]
    assert token.startswith("pmat_") and created["display_prefix"] == token[:12]
    assert created["scopes"] == ["read", "write"]

    me = await db_client.get("/v1/me", headers=bearer(token))
    assert me.status_code == 200 and me.json()["email"] == "ada@example.com"

    listed = (await db_client.get("/v1/me/tokens", headers=ada.headers)).json()
    assert [t["name"] for t in listed] == ["laptop"]
    assert "token" not in listed[0]  # never shown again
    assert listed[0]["last_used_at"] is not None

    # A token can revoke itself (CLI logout); then it stops working.
    res = await db_client.delete(f"/v1/me/tokens/{created['id']}", headers=bearer(token))
    assert res.status_code == 204
    assert (await db_client.get("/v1/me", headers=bearer(token))).status_code == 401
    assert (await db_client.get("/v1/me/tokens", headers=ada.headers)).json() == []


async def test_read_only_token_cannot_write(signup, db_client: AsyncClient) -> None:
    ada = await signup()
    token = (await make_token(db_client, ada.headers, scopes=["read"]))["token"]
    assert (await db_client.get("/v1/workspaces", headers=bearer(token))).status_code == 200
    res = await db_client.post("/v1/workspaces", json={"name": "Nope"}, headers=bearer(token))
    assert res.status_code == 403


async def test_api_tokens_cannot_mint_credentials(signup, db_client: AsyncClient) -> None:
    ada = await signup()
    token = (await make_token(db_client, ada.headers))["token"]
    res = await db_client.post("/v1/me/tokens", json={"name": "escalate"}, headers=bearer(token))
    assert res.status_code == 403


async def test_expired_token_is_rejected(
    signup, db_client: AsyncClient, db_session: AsyncSession
) -> None:
    ada = await signup()
    created = await make_token(db_client, ada.headers)
    await db_session.execute(
        update(ApiToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db_session.commit()
    assert (await db_client.get("/v1/me", headers=bearer(created["token"]))).status_code == 401


async def test_tokens_are_private_to_their_owner(signup, db_client: AsyncClient) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    created = await make_token(db_client, ada.headers)
    assert (await db_client.get("/v1/me/tokens", headers=bob.headers)).json() == []
    res = await db_client.delete(f"/v1/me/tokens/{created['id']}", headers=bob.headers)
    assert res.status_code == 404


async def test_unknown_api_token(db_client: AsyncClient) -> None:
    assert (await db_client.get("/v1/me", headers=bearer("pmat_nope"))).status_code == 401


# -- device login -----------------------------------------------------------------------


async def start(client: AsyncClient) -> dict:
    res = await client.post("/v1/auth/device/code", json={"client_name": "pmagent CLI"})
    assert res.status_code == 200, res.text
    return res.json()


async def poll(client: AsyncClient, device_code: str):
    return await client.post("/v1/auth/device/token", json={"device_code": device_code})


async def allow_next_poll(db_session: AsyncSession) -> None:
    """Skip the poll interval instead of sleeping."""
    await db_session.execute(update(DeviceAuthorization).values(last_polled_at=None))
    await db_session.commit()


async def test_device_login(signup, db_client: AsyncClient, db_session: AsyncSession) -> None:
    ada = await signup()
    device = await start(db_client)
    code = device["user_code"]
    assert len(code) == 9 and code[4] == "-"
    assert device["verification_uri"] == "http://app.test/device"
    assert device["interval"] == 5

    pending = await poll(db_client, device["device_code"])
    assert pending.status_code == 400 and pending.json()["type"].endswith("/authorization_pending")
    too_fast = await poll(db_client, device["device_code"])
    assert too_fast.json()["type"].endswith("/slow_down")

    # In the web app, Ada types the code (any case, dash optional) and approves.
    typed = code.replace("-", "").lower()
    lookup = await db_client.post("/v1/auth/device/lookup", json={"user_code": typed}, headers=ada.headers)
    assert lookup.status_code == 200 and lookup.json()["client_name"] == "pmagent CLI"
    res = await db_client.post("/v1/auth/device/approve", json={"user_code": code}, headers=ada.headers)
    assert res.status_code == 204

    await allow_next_poll(db_session)
    issued = await poll(db_client, device["device_code"])
    assert issued.status_code == 200
    token = issued.json()["token"]
    me = await db_client.get("/v1/me", headers=bearer(token))
    assert me.json()["email"] == "ada@example.com"

    # The device code is single use, and the new token shows up in Ada's list.
    again = await poll(db_client, device["device_code"])
    assert again.json()["type"].endswith("/invalid_grant")
    names = [t["name"] for t in (await db_client.get("/v1/me/tokens", headers=ada.headers)).json()]
    assert names == ["pmagent CLI"]


async def test_device_login_denied(signup, db_client: AsyncClient) -> None:
    ada = await signup()
    device = await start(db_client)
    res = await db_client.post(
        "/v1/auth/device/deny", json={"user_code": device["user_code"]}, headers=ada.headers
    )
    assert res.status_code == 204
    denied = await poll(db_client, device["device_code"])
    assert denied.json()["type"].endswith("/access_denied")


async def test_device_code_expires(
    signup, db_client: AsyncClient, db_session: AsyncSession
) -> None:
    ada = await signup()
    device = await start(db_client)
    await db_session.execute(
        update(DeviceAuthorization).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db_session.commit()

    approve = await db_client.post(
        "/v1/auth/device/approve", json={"user_code": device["user_code"]}, headers=ada.headers
    )
    assert approve.status_code == 404
    expired = await poll(db_client, device["device_code"])
    assert expired.json()["type"].endswith("/expired_token")


async def test_only_a_signed_in_session_can_approve(signup, db_client: AsyncClient) -> None:
    ada = await signup()
    api_token = (await make_token(db_client, ada.headers))["token"]
    device = await start(db_client)
    body = {"user_code": device["user_code"]}

    assert (await db_client.post("/v1/auth/device/approve", json=body)).status_code == 401
    res = await db_client.post("/v1/auth/device/approve", json=body, headers=bearer(api_token))
    assert res.status_code == 403


async def test_unknown_codes(signup, db_client: AsyncClient) -> None:
    ada = await signup()
    lookup = await db_client.post(
        "/v1/auth/device/lookup", json={"user_code": "BCDF-GHJK"}, headers=ada.headers
    )
    assert lookup.status_code == 404
    assert (await poll(db_client, "not-a-device-code")).json()["type"].endswith("/invalid_grant")
