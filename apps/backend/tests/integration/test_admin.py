"""The Admin app's accounts: sign-up by proving ownership, its own sign-in, rotating
refresh tokens, and the workspace-scoped reads it reaches."""
from typing import Any

from httpx import AsyncClient


async def _admin(db_client: AsyncClient, owner: Any, email: str = "ops@example.com") -> dict[str, str]:
    """Create an admin through the API and return its bearer header."""
    res = await db_client.post(
        "/v1/admin/signup",
        json={
            "owner_email": owner.email,
            "owner_password": owner.password,
            "email": email,
            "name": "Ops",
            "password": "admin secret 123",
        },
    )
    assert res.status_code == 201, res.text
    tokens = res.json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def test_signup_needs_the_owners_credentials(db_client: AsyncClient, signup) -> None:
    owner = await signup()
    res = await db_client.post(
        "/v1/admin/signup",
        json={
            "owner_email": owner.email,
            "owner_password": "not the password",
            "email": "ops@example.com",
            "name": "Ops",
            "password": "admin secret 123",
        },
    )
    assert res.status_code == 401


async def test_admin_me_observe_and_convert(db_client: AsyncClient, signup) -> None:
    owner = await signup()
    headers = await _admin(db_client, owner)

    me = await db_client.get("/v1/admin/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["workspace"]["kind"] == "personal"
    assert me.json()["email"] == "ops@example.com"

    for path in ("/v1/admin/observe/overview", "/v1/admin/observe/runs", "/v1/admin/audit"):
        res = await db_client.get(path, headers=headers)
        assert res.status_code == 200, f"{path}: {res.text}"

    # A personal workspace becomes an organisation through the admin too.
    res = await db_client.post("/v1/admin/convert-to-organization", json={}, headers=headers)
    assert res.status_code == 200, res.text
    me = await db_client.get("/v1/admin/me", headers=headers)
    assert me.json()["workspace"]["kind"] == "organization"


async def test_app_tokens_and_missing_auth_are_rejected(db_client: AsyncClient, signup) -> None:
    owner = await signup()
    res = await db_client.get("/v1/admin/me")
    assert res.status_code == 401
    # An app user's access token is not an admin token.
    res = await db_client.get("/v1/admin/me", headers=owner.headers)
    assert res.status_code == 401


async def test_login_and_duplicate_admin_email(db_client: AsyncClient, signup) -> None:
    owner = await signup()
    await _admin(db_client, owner)

    res = await db_client.post("/v1/admin/login", json={"email": "ops@example.com", "password": "wrong"})
    assert res.status_code == 401

    res = await db_client.post("/v1/admin/login", json={"email": "ops@example.com", "password": "admin secret 123"})
    assert res.status_code == 200, res.text
    assert res.json()["access_token"]

    # The same admin email can't be registered twice.
    res = await db_client.post(
        "/v1/admin/signup",
        json={
            "owner_email": owner.email,
            "owner_password": owner.password,
            "email": "ops@example.com",
            "name": "Ops Two",
            "password": "another secret 123",
        },
    )
    assert res.status_code == 409


async def test_refresh_rotates_and_logout_revokes(db_client: AsyncClient, signup) -> None:
    owner = await signup()
    await _admin(db_client, owner)
    login = await db_client.post("/v1/admin/login", json={"email": "ops@example.com", "password": "admin secret 123"})
    tokens = login.json()

    # The access token works, then refresh gives a new pair.
    assert (await db_client.get("/v1/admin/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})).status_code == 200
    res = await db_client.post("/v1/admin/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert res.status_code == 200, res.text
    rotated = res.json()
    assert rotated["refresh_token"] != tokens["refresh_token"]

    # Rotation: the old refresh token is dead; the new one works.
    assert (await db_client.post("/v1/admin/refresh", json={"refresh_token": tokens["refresh_token"]})).status_code == 401
    assert (await db_client.post("/v1/admin/refresh", json={"refresh_token": rotated["refresh_token"]})).status_code == 200

    # Logout revokes the session: refreshing afterwards is a 401.
    res = await db_client.post(
        "/v1/admin/logout",
        json={"refresh_token": rotated["refresh_token"]},
        headers={"Authorization": f"Bearer {rotated['access_token']}"},
    )
    assert res.status_code == 204
    assert (await db_client.post("/v1/admin/refresh", json={"refresh_token": rotated["refresh_token"]})).status_code == 401
