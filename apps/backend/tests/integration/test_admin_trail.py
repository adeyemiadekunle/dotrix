"""The admin console's trail: every sign-in and change to admin accounts is recorded once, with who
did it and to whom, and never a password or token."""
import argparse
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend import admin_cli
from dotrix_backend.core.email import OutboxEmailSender
from dotrix_backend.core.jobs import JobContext
from dotrix_backend.jobs import cleanup_expired
from dotrix_backend.modules.admin.models import AdminEvent, AdminUser

from .test_admin import ADMIN, _admin
from .test_admin_accounts import PASSWORD, _browser, _invite_and_accept, _invite_token  # noqa: F401

NEW_PASSWORD = "a much newer password"


@pytest.fixture(autouse=True)
def admin_url(db_client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    db_client.headers["X-Requested-With"] = "dotrix-admin"
    monkeypatch.setattr(db_client._transport.app.state.settings, "admin_url", "https://admin.example.com")  # type: ignore[attr-defined]


async def _events(session: AsyncSession) -> list[AdminEvent]:
    return list((await session.scalars(select(AdminEvent).order_by(AdminEvent.created_at, AdminEvent.id))).all())


def _summary(events: list[AdminEvent]) -> list[tuple[str, str | None, str | None]]:
    return [(e.action, e.actor_email, e.target_email) for e in events]


async def test_signup_sign_in_and_sign_out(db_client: AsyncClient, db_session: AsyncSession) -> None:
    await _admin(db_client)  # sign-up signs in
    other = _browser(db_client)
    assert (await other.post("/v1/admin/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})).status_code == 204
    assert (await other.post("/v1/admin/logout")).status_code == 204
    events = await _events(db_session)
    assert _summary(events) == [
        ("admin.created", ADMIN["email"], None),
        ("admin.signed_in", ADMIN["email"], None),
        ("admin.signed_out", ADMIN["email"], None),
    ]
    assert all(e.admin_user_id is not None and e.ip for e in events)


async def test_a_failed_sign_in_keeps_the_tried_email_and_no_account(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _admin(db_client)
    other = _browser(db_client)
    assert (await other.post("/v1/admin/login", json={"email": ADMIN["email"], "password": "wrong guess 1234"})).status_code == 401
    assert (await other.post("/v1/admin/login", json={"email": "Nobody@Example.com", "password": "wrong guess 1234"})).status_code == 401
    failed = [e for e in await _events(db_session) if e.action == "admin.sign_in_failed"]
    assert [(e.actor_email, e.admin_user_id) for e in failed] == [(ADMIN["email"], None), ("nobody@example.com", None)]
    assert "wrong guess" not in repr([vars(e) for e in failed])


async def test_invites_roles_disabling_and_removal_are_recorded_once_each(
    db_client: AsyncClient, db_session: AsyncSession, outbox: OutboxEmailSender
) -> None:
    await _admin(db_client)
    owner_email = ADMIN["email"]
    viewer = await _invite_and_accept(db_client, outbox, "vi@example.com")
    pending = (await db_client.post("/v1/admin/admins/invites", json={"email": "gone@example.com", "role": "viewer"})).json()
    assert (await db_client.delete(f"/v1/admin/admins/invites/{pending['id']}")).status_code == 204
    assert (await db_client.delete(f"/v1/admin/admins/invites/{pending['id']}")).status_code == 204  # already revoked: no second row
    viewer_id = next(a["id"] for a in (await db_client.get("/v1/admin/admins")).json() if a["email"] == "vi@example.com")
    assert (await viewer.post("/v1/admin/me/sessions/revoke-others")).status_code == 204
    for body in ({"role": "owner"}, {"role": "owner"}, {"disabled": True}, {"disabled": True}, {"disabled": False}):
        assert (await db_client.patch(f"/v1/admin/admins/{viewer_id}", json=body)).status_code == 200
    assert (await db_client.delete(f"/v1/admin/admins/{viewer_id}")).status_code == 204

    assert _summary(await _events(db_session)) == [
        ("admin.created", owner_email, None),
        ("admin.invited", owner_email, "vi@example.com"),
        ("admin.created", "vi@example.com", None),
        ("admin.invited", owner_email, "gone@example.com"),
        ("admin.invite_revoked", owner_email, "gone@example.com"),
        ("admin.sessions_revoked", "vi@example.com", None),
        ("admin.role_changed", owner_email, "vi@example.com"),
        ("admin.disabled", owner_email, "vi@example.com"),
        ("admin.enabled", owner_email, "vi@example.com"),
        ("admin.removed", owner_email, "vi@example.com"),
    ]
    # The removed account's own rows keep their emails but lose the link to it.
    assert await db_session.scalar(select(AdminUser.id).where(AdminUser.email == "vi@example.com")) is None
    assert all(e.admin_user_id is None for e in await _events(db_session) if e.actor_email == "vi@example.com")


async def test_password_change_and_the_command_line(
    db_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _admin(db_client)
    res = await db_client.post(
        "/v1/admin/me/password", json={"current_password": ADMIN["password"], "new_password": NEW_PASSWORD}
    )
    assert res.status_code == 204, res.text
    # A wrong current password changes nothing and records nothing.
    bad = await db_client.post("/v1/admin/me/password", json={"current_password": "not it at all", "new_password": NEW_PASSWORD})
    assert bad.status_code == 403
    args = argparse.Namespace(command="create", email="Ops@Example.com", name="Ops")
    await admin_cli.execute(db_session, args, lambda: "command line password 1")
    await admin_cli.execute(db_session, argparse.Namespace(command="reset-password", email="ops@example.com"), lambda: "another cli password")
    await db_session.commit()
    assert _summary(await _events(db_session)) == [
        ("admin.created", ADMIN["email"], None),
        ("admin.password_changed", ADMIN["email"], None),
        ("admin.created", "command line", "ops@example.com"),
        ("admin.password_reset", "command line", "ops@example.com"),
    ]


async def test_the_storage_limit_change_is_recorded_without_the_old_audit_changing(
    db_client: AsyncClient, db_session: AsyncSession, signup
) -> None:
    owner = await signup()
    ws = (await db_client.get("/v1/workspaces", headers=owner.headers)).json()[0]
    await _admin(db_client)
    body = {"workspace_id": ws["id"], "storage_limit_mb": 5}
    assert (await db_client.put("/v1/admin/storage-limit", json=body)).status_code == 204
    assert (await db_client.put("/v1/admin/storage-limit", json=body)).status_code == 204  # unchanged: nothing recorded
    events = [e for e in await _events(db_session) if e.action == "admin.storage_limit_changed"]
    assert [(e.actor_email, e.workspace) for e in events] == [(ADMIN["email"], ws["slug"])]
    from dotrix_backend.modules.audit.models import AuditEvent

    assert await db_session.scalar(select(AuditEvent.id).where(AuditEvent.action == "workspace.storage_limit_updated"))


async def test_the_trail_holds_no_secrets_and_pages_and_filters(
    db_client: AsyncClient, db_session: AsyncSession, outbox: OutboxEmailSender
) -> None:
    await _admin(db_client)
    viewer = await _invite_and_accept(db_client, outbox, "vi@example.com")
    token = _invite_token(outbox, "vi@example.com")
    await _browser(db_client).post("/v1/admin/login", json={"email": ADMIN["email"], "password": "a wrong password!"})
    await db_client.post("/v1/admin/me/password", json={"current_password": ADMIN["password"], "new_password": NEW_PASSWORD})

    res = await db_client.get("/v1/admin/trail?limit=200")
    assert res.status_code == 200
    page = res.json()
    secrets = [ADMIN["password"], NEW_PASSWORD, PASSWORD, "a wrong password!", token]
    assert not any(secret in res.text for secret in secrets)
    stored = repr([vars(e) for e in await _events(db_session)])
    assert not any(secret in stored for secret in secrets)
    assert set(page["items"][0]) == {"id", "action", "actor_email", "target_email", "workspace", "ip", "created_at"}
    assert page["total"] == len(page["items"]) == 5  # created, invited, created, failed, password changed
    assert page["items"][0]["action"] == "admin.password_changed"  # newest first

    small = (await db_client.get("/v1/admin/trail?limit=2&offset=1")).json()
    assert small["total"] == 5 and len(small["items"]) == 2
    only = (await db_client.get("/v1/admin/trail?action=admin.sign_in")).json()
    assert [e["action"] for e in only["items"]] == ["admin.sign_in_failed"] and only["total"] == 1
    assert (await db_client.get("/v1/admin/trail?action=admin.created")).json()["total"] == 2

    assert (await viewer.get("/v1/admin/trail")).status_code == 403
    assert (await _browser(db_client).get("/v1/admin/trail")).status_code == 401


async def test_old_events_are_cleaned_up_after_400_days(
    db_client: AsyncClient, db_session: AsyncSession, outbox: OutboxEmailSender
) -> None:
    await _admin(db_client)
    app = db_client._transport.app  # type: ignore[attr-defined]
    ctx = JobContext(app.state.runner.session_factory, app.state.settings, outbox)
    assert (await cleanup_expired(ctx, now=(datetime.now(UTC) + timedelta(days=399)).isoformat()))["admin_events"] == 0
    assert (await cleanup_expired(ctx, now=(datetime.now(UTC) + timedelta(days=401)).isoformat()))["admin_events"] == 1
