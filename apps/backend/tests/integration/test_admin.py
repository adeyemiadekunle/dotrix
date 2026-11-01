"""The admin console's accounts (bootstrap sign-up, its own sign-in, rotating refresh cookies)
and the platform-wide observability it reads: every workspace, never what people wrote."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.modules.agents.models import RunStatus
from dotrix_backend.modules.audit.models import AuthorType
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.coding.models import CodingRunStatus

from .test_observe import _chat_run, _coding_run

ADMIN = {"email": "admin@example.com", "name": "Admin", "password": "admin secret 123"}


@pytest.fixture(autouse=True)
def admin_header(db_client: AsyncClient) -> None:
    db_client.headers["X-Requested-With"] = "dotrix-admin"


async def _admin(db_client: AsyncClient) -> None:
    """Bootstrap the admin account and sign it in (httpOnly cookies carry it after)."""
    res = await db_client.post("/v1/admin/signup", json=ADMIN)
    assert res.status_code == 201, res.text
    assert "access_token" not in res.text and "refresh_token" not in res.text
    assert res.cookies.get("dtx_admin_access") and res.cookies.get("dtx_admin_refresh")


async def test_bootstrap_only_while_no_account_exists(db_client: AsyncClient) -> None:
    assert (await db_client.get("/v1/admin/bootstrap")).json()["enabled"] is True
    await _admin(db_client)
    assert (await db_client.get("/v1/admin/bootstrap")).json()["enabled"] is False
    assert (await db_client.post("/v1/admin/signup", json=ADMIN)).status_code == 403


async def test_me_and_the_platform_reads(db_client: AsyncClient, db_session: AsyncSession, signup) -> None:
    owner = await signup()
    other = await signup(email="other@example.com", name="Other")
    await _admin(db_client)

    me = (await db_client.get("/v1/admin/me")).json()
    assert me["email"] == "admin@example.com" and me["workspace"] is None

    ws = (await db_client.get("/v1/workspaces", headers=owner.headers)).json()[0]
    base = f"/v1/workspaces/{ws['id']}"
    project = (await db_client.post(f"{base}/projects", json={"key": "KUN", "name": "Kunemi"}, headers=owner.headers)).json()
    issue = (await db_client.post(f"{base}/projects/{project['id']}/issues", json={"title": "Refunds"}, headers=owner.headers)).json()
    other_ws = (await db_client.get("/v1/workspaces", headers=other.headers)).json()[0]
    other_project = (
        await db_client.post(f"/v1/workspaces/{other_ws['id']}/projects", json={"key": "OTH", "name": "Other"}, headers=other.headers)
    ).json()
    now = datetime.now(UTC)
    db_session.add(_chat_run(ws["id"], project["id"], owner, title="My private question", message="secret words", input_tokens=10, output_tokens=4))
    db_session.add(
        _chat_run(
            other_ws["id"], other_project["id"], other, title="Theirs", status=RunStatus.FAILED,
            error="Provider refused: rate limit\ntrace", error_kind="model_limit", finished_at=now,
        )
    )
    db_session.add(
        _chat_run(other_ws["id"], other_project["id"], other, status=RunStatus.RUNNING, lease_expires_at=now - timedelta(minutes=3))
    )
    db_session.add(
        _coding_run(
            ws["id"], project["id"], issue["id"], owner, issue_key=issue["key"], status=CodingRunStatus.FAILED,
            error="the sandbox died", started_at=now - timedelta(minutes=4), finished_at=now, cost_usd=0.5,
        )
    )
    db_session.add(
        _coding_run(
            ws["id"], project["id"], issue["id"], owner, issue_key=issue["key"],
            started_at=now - timedelta(minutes=2), finished_at=now, input_tokens=100, output_tokens=20,
        )
    )
    AuditLog(db_session).record(
        workspace_id=uuid.UUID(ws["id"]), project_id=None, action="sandbox_network.updated", target="x",
        actor_type=AuthorType.USER, actor_user_id=uuid.UUID(owner.id), details={"added": ["secret.example.com"]},
    )
    await db_session.commit()

    health = (await db_client.get("/v1/admin/observe/health")).json()
    assert health["version"] and health["database_ms"] >= 0 and health["runs_running"] == 1
    assert [(s["kind"], s["workspace"]) for s in health["stuck"]] == [("chat", other_ws["slug"])]
    assert health["failed_24h"] == 2 and health["finished_24h"] == 3

    counts = (await db_client.get("/v1/admin/observe/counts")).json()
    assert counts["workspaces"] >= 2 and counts["people"] >= 2 and counts["people_active"] == 2
    assert counts["workspaces_active"] == 2 and counts["projects"] == 2

    days = (await db_client.get("/v1/admin/observe/trends?days=3")).json()
    assert len(days) == 3 and days[-1]["day"] == now.date().isoformat()
    assert days[-1]["chat_runs"] == 3 and days[-1]["chat_failed"] == 1
    assert days[-1]["coding_runs"] == 2 and days[-1]["coding_failed"] == 1 and days[-1]["coding_cost_usd"] == 0.5

    failures = (await db_client.get("/v1/admin/observe/failures")).json()
    assert [(g["key"], g["count"]) for g in failures["chat_kinds"]] == [("model_limit", 1)]
    lines = {(g["kind"], g["key"]) for g in failures["messages"]}
    assert lines == {("chat", "Provider refused: rate limit"), ("coding", "the sandbox died")}

    coding = (await db_client.get("/v1/admin/observe/coding")).json()
    assert len(coding) == 1 and coding[0]["turns"] == 2 and coding[0]["failed"] == 1 and coding[0]["prs"] == 1
    assert coding[0]["p50_seconds"] == 180.0

    workspaces = (await db_client.get("/v1/admin/observe/workspaces")).json()
    mine = next(w for w in workspaces if w["slug"] == ws["slug"])
    assert mine["chat_runs"] == 1 and mine["coding_runs"] == 2 and mine["failed"] == 1 and mine["projects"] == 1

    # Runs and audit cover every workspace but never carry what people wrote.
    res = await db_client.get("/v1/admin/observe/runs")
    assert res.status_code == 200 and "secret words" not in res.text and "My private question" not in res.text
    page = res.json()
    runs = page["items"]
    assert page["total"] == 5 and len(runs) == 5
    assert {r["workspace"] for r in runs} == {ws["slug"], other_ws["slug"]}
    assert {r["label"] for r in runs if r["kind"] == "chat"} == {"KUN", "OTH"}
    # Pages of two: the second starts where the first ended, and the last has what's left.
    first = (await db_client.get("/v1/admin/observe/runs?limit=2")).json()
    second = (await db_client.get("/v1/admin/observe/runs?limit=2&offset=2")).json()
    last = (await db_client.get("/v1/admin/observe/runs?limit=2&offset=4")).json()
    assert [r["id"] for r in first["items"] + second["items"] + last["items"]] == [r["id"] for r in runs]
    assert first["total"] == second["total"] == last["total"] == 5 and len(last["items"]) == 1
    failed = (await db_client.get("/v1/admin/observe/runs?failed=true")).json()
    assert {r["status"] for r in failed["items"]} == {"failed"} and failed["total"] == 2
    coding = (await db_client.get("/v1/admin/observe/runs?kind=coding")).json()
    assert coding["total"] == 2 and {r["kind"] for r in coding["items"]} == {"coding"}

    res = await db_client.get("/v1/admin/audit?action=sandbox_")
    assert res.status_code == 200 and "secret.example.com" not in res.text
    assert [(e["action"], e["workspace"]) for e in res.json()["items"]] == [("sandbox_network.updated", ws["slug"])]
    assert res.json()["total"] == 1
    assert (await db_client.get("/v1/admin/audit?action=nothing.")).json() == {"items": [], "total": 0}
    everything = (await db_client.get("/v1/admin/audit?limit=1")).json()
    assert len(everything["items"]) == 1 and everything["total"] >= 1


async def test_app_tokens_and_missing_auth_are_rejected(db_client: AsyncClient, signup) -> None:
    owner = await signup()
    assert (await db_client.get("/v1/admin/me")).status_code == 401
    assert (await db_client.get("/v1/admin/me", headers=owner.headers)).status_code == 401


async def test_login_and_lockout(db_client: AsyncClient) -> None:
    await _admin(db_client)
    assert (await db_client.post("/v1/admin/login", json={"email": "admin@example.com", "password": "wrong"})).status_code == 401
    res = await db_client.post("/v1/admin/login", json={"email": "admin@example.com", "password": "admin secret 123"})
    assert res.status_code == 204 and res.cookies.get("dtx_admin_access")


async def test_refresh_rotates_and_logout_revokes(db_client: AsyncClient) -> None:
    await _admin(db_client)
    first = db_client.cookies.get("dtx_admin_refresh")
    assert (await db_client.post("/v1/admin/refresh")).status_code == 204
    assert db_client.cookies.get("dtx_admin_refresh") != first
    # The rotated-out refresh token is dead.
    assert (
        await db_client.post("/v1/admin/refresh", headers={"Cookie": f"dtx_admin_refresh={first}"})
    ).status_code == 401
    access = db_client.cookies.get("dtx_admin_access")
    assert (await db_client.post("/v1/admin/logout")).status_code == 204
    assert (await db_client.get("/v1/admin/me", headers={"Cookie": f"dtx_admin_access={access}"})).status_code == 401


async def test_admin_cookie_writes_require_csrf_header(db_client: AsyncClient) -> None:
    await _admin(db_client)
    res = await db_client.post("/v1/admin/logout", headers={"X-Requested-With": ""})
    assert res.status_code == 403
