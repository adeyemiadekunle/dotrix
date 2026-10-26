"""The Ops app's accounts: sign-up by proving ownership, its own sign-in, rotating
refresh tokens, and the workspace-scoped reads it reaches."""
from typing import Any

import pytest
from httpx import AsyncClient


@pytest.fixture(autouse=True)
def ops_header(db_client: AsyncClient) -> None:
    db_client.headers["X-Requested-With"] = "dotrix-ops"


async def _ops(db_client: AsyncClient, owner: Any, email: str = "ops@example.com") -> dict[str, str]:
    """Create an ops session. The API authenticates via httpOnly cookies, not bearer tokens."""
    res = await db_client.post(
        "/v1/ops/signup",
        json={
            "owner_email": owner.email,
            "owner_password": owner.password,
            "email": email,
            "name": "Ops",
            "password": "ops secret 123",
        },
    )
    assert res.status_code == 201, res.text
    assert "access_token" not in res.text and "refresh_token" not in res.text
    assert res.cookies.get("dtx_ops_access") and res.cookies.get("dtx_ops_refresh")
    assert all("httponly" in cookie.lower() for cookie in res.headers.get_list("set-cookie"))
    return {}


async def test_signup_needs_the_owners_credentials(db_client: AsyncClient, signup) -> None:
    owner = await signup()
    res = await db_client.post(
        "/v1/ops/signup",
        json={
            "owner_email": owner.email,
            "owner_password": "not the password",
            "email": "ops@example.com",
            "name": "Ops",
            "password": "ops secret 123",
        },
    )
    assert res.status_code == 401


async def test_ops_me_observe_and_create_organization(db_client: AsyncClient, signup) -> None:
    owner = await signup()
    headers = await _ops(db_client, owner)

    me = await db_client.get("/v1/ops/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["workspace"]["kind"] == "personal"
    assert me.json()["email"] == "ops@example.com"

    for path in ("/v1/ops/observe/overview", "/v1/ops/observe/runs", "/v1/ops/audit"):
        res = await db_client.get(path, headers=headers)
        assert res.status_code == 200, f"{path}: {res.text}"

    # The ops can create an organisation — a new workspace, not a conversion: the personal
    # workspace this ops is bound to stays personal.
    res = await db_client.post("/v1/ops/organization", json={"name": "Kunemi"}, headers=headers)
    assert res.status_code == 201, res.text
    assert res.json()["kind"] == "organization" and res.json()["role"] == "owner"
    me = await db_client.get("/v1/ops/me", headers=headers)
    assert me.json()["workspace"]["kind"] == "personal"
    listed = (await db_client.get("/v1/workspaces", headers=owner.headers)).json()
    assert any(w["name"] == "Kunemi" and w["kind"] == "organization" for w in listed)


async def test_app_tokens_and_missing_auth_are_rejected(db_client: AsyncClient, signup) -> None:
    owner = await signup()
    res = await db_client.get("/v1/ops/me")
    assert res.status_code == 401
    # An app user's access token is not an ops token.
    res = await db_client.get("/v1/ops/me", headers=owner.headers)
    assert res.status_code == 401


async def test_login_and_duplicate_ops_email(db_client: AsyncClient, signup) -> None:
    owner = await signup()
    await _ops(db_client, owner)

    res = await db_client.post("/v1/ops/login", json={"email": "ops@example.com", "password": "wrong"})
    assert res.status_code == 401

    res = await db_client.post("/v1/ops/login", json={"email": "ops@example.com", "password": "ops secret 123"})
    assert res.status_code == 204, res.text
    assert not res.content

    # The same ops email can't be registered twice.
    res = await db_client.post(
        "/v1/ops/signup",
        json={
            "owner_email": owner.email,
            "owner_password": owner.password,
            "email": "ops@example.com",
            "name": "Ops Two",
            "password": "another secret 123",
        },
    )
    assert res.status_code == 409


async def test_signup_picks_the_personal_workspace_when_owner_has_both(db_client: AsyncClient, signup) -> None:
    """Converting gives the owner a new personal workspace alongside the organisation; the
    ops account must bind to the personal one, not whichever membership comes first."""
    owner = await signup()
    personal = (await db_client.get("/v1/workspaces", headers=owner.headers)).json()[0]
    res = await db_client.post(f"/v1/workspaces/{personal['id']}/convert-to-organization", json={}, headers=owner.headers)
    assert res.status_code == 200, res.text

    headers = await _ops(db_client, owner)
    me = await db_client.get("/v1/ops/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["workspace"]["kind"] == "personal"


async def test_refresh_rotates_and_logout_revokes(db_client: AsyncClient, signup) -> None:
    owner = await signup()
    await _ops(db_client, owner)
    login = await db_client.post("/v1/ops/login", json={"email": "ops@example.com", "password": "ops secret 123"})
    assert login.status_code == 204 and not login.content
    first_cookie = db_client.cookies.get("dtx_ops_refresh")
    access_cookie = db_client.cookies.get("dtx_ops_access")
    assert first_cookie

    # The access cookie works, then refresh rotates the cookie; both stay httpOnly.
    assert (await db_client.get("/v1/ops/me")).status_code == 200
    res = await db_client.post("/v1/ops/refresh")
    assert res.status_code == 204 and not res.content
    assert db_client.cookies.get("dtx_ops_refresh") != first_cookie

    # Rotation: the previous refresh cookie is dead; the new one works.
    stale = await db_client.post("/v1/ops/refresh", headers={"Cookie": f"dtx_ops_refresh={first_cookie}"})
    assert stale.status_code == 401
    assert (await db_client.post("/v1/ops/refresh")).status_code == 204

    # Logout revokes the session even if the refresh cookie has gone missing.
    dead = db_client.cookies.get("dtx_ops_refresh")
    logout = await db_client.post("/v1/ops/logout", headers={"Cookie": f"dtx_ops_access={access_cookie}"})
    assert logout.status_code == 204
    assert (await db_client.get("/v1/ops/me", headers={"Cookie": f"dtx_ops_access={access_cookie}"})).status_code == 401
    assert (await db_client.post("/v1/ops/refresh", headers={"Cookie": f"dtx_ops_refresh={dead}"})).status_code == 401


async def test_ops_cookie_writes_require_csrf_header(db_client: AsyncClient, signup) -> None:
    owner = await signup()
    await _ops(db_client, owner)
    res = await db_client.post("/v1/ops/organization", json={"name": "Cross-site"}, headers={"X-Requested-With": ""})
    assert res.status_code == 403
