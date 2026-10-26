"""The Ops console's accounts: bootstrap sign-up, its own sign-in, rotating refresh
cookies, and the platform-wide reads it reaches."""
import pytest
from httpx import AsyncClient

OPS = {"email": "ops@example.com", "name": "Ops", "password": "ops secret 123"}


@pytest.fixture(autouse=True)
def ops_header(db_client: AsyncClient) -> None:
    db_client.headers["X-Requested-With"] = "dotrix-ops"


async def _ops(db_client: AsyncClient) -> None:
    """Bootstrap the ops account and sign it in (httpOnly cookies carry it after)."""
    res = await db_client.post("/v1/ops/signup", json=OPS)
    assert res.status_code == 201, res.text
    assert "access_token" not in res.text and "refresh_token" not in res.text
    assert res.cookies.get("dtx_ops_access") and res.cookies.get("dtx_ops_refresh")


async def test_bootstrap_only_while_no_account_exists(db_client: AsyncClient) -> None:
    assert (await db_client.get("/v1/ops/bootstrap")).json()["enabled"] is True
    await _ops(db_client)
    assert (await db_client.get("/v1/ops/bootstrap")).json()["enabled"] is False
    assert (await db_client.post("/v1/ops/signup", json=OPS)).status_code == 403


async def test_me_observe_and_audit_are_platform_wide(db_client: AsyncClient, signup) -> None:
    owner = await signup()
    await signup(email="other@example.com", name="Other")
    await _ops(db_client)

    me = (await db_client.get("/v1/ops/me")).json()
    assert me["email"] == "ops@example.com" and me["workspace"] is None

    # Two users' runs both show up in the platform overview, regardless of workspace.
    ws = (await db_client.get("/v1/workspaces", headers=owner.headers)).json()[0]
    base = f"/v1/workspaces/{ws['id']}"
    project = (await db_client.post(f"{base}/projects", json={"key": "KUN", "name": "Kunemi"}, headers=owner.headers)).json()
    assert project["id"]
    res = await db_client.get("/v1/ops/observe/overview")
    assert res.status_code == 200, res.text
    res = await db_client.get("/v1/ops/observe/runs")
    assert res.status_code == 200, res.text
    assert (await db_client.get("/v1/ops/audit")).status_code == 200
    # It counts workspaces and people across the deployment.
    overview = (await db_client.get("/v1/ops/observe/overview")).json()
    assert overview["counts"]["members"] >= 2


async def test_app_tokens_and_missing_auth_are_rejected(db_client: AsyncClient, signup) -> None:
    owner = await signup()
    assert (await db_client.get("/v1/ops/me")).status_code == 401
    assert (await db_client.get("/v1/ops/me", headers=owner.headers)).status_code == 401


async def test_login_and_lockout(db_client: AsyncClient) -> None:
    await _ops(db_client)
    assert (await db_client.post("/v1/ops/login", json={"email": "ops@example.com", "password": "wrong"})).status_code == 401
    res = await db_client.post("/v1/ops/login", json={"email": "ops@example.com", "password": "ops secret 123"})
    assert res.status_code == 204 and res.cookies.get("dtx_ops_access")


async def test_refresh_rotates_and_logout_revokes(db_client: AsyncClient) -> None:
    await _ops(db_client)
    first = db_client.cookies.get("dtx_ops_refresh")
    assert (await db_client.post("/v1/ops/refresh")).status_code == 204
    assert db_client.cookies.get("dtx_ops_refresh") != first
    # The rotated-out refresh token is dead.
    assert (
        await db_client.post("/v1/ops/refresh", headers={"Cookie": f"dtx_ops_refresh={first}"})
    ).status_code == 401
    access = db_client.cookies.get("dtx_ops_access")
    assert (await db_client.post("/v1/ops/logout")).status_code == 204
    assert (await db_client.get("/v1/ops/me", headers={"Cookie": f"dtx_ops_access={access}"})).status_code == 401


async def test_ops_cookie_writes_require_csrf_header(db_client: AsyncClient) -> None:
    await _ops(db_client)
    res = await db_client.post("/v1/ops/logout", headers={"X-Requested-With": ""})
    assert res.status_code == 403
