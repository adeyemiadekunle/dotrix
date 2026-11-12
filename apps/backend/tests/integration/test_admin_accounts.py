"""Several admins: invites, the two roles, disabling and removing, and changing your own password."""
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.email import OutboxEmailSender
from dotrix_backend.modules.admin.models import AdminInvite, AdminSession, AdminUser

from .test_admin import ADMIN, _admin

HEALTH = "/v1/admin/observe/health"
PASSWORD = "a viewer's own password"
URL = "https://admin.example.com"


@pytest.fixture(autouse=True)
def admin_url(db_client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    db_client.headers["X-Requested-With"] = "dotrix-admin"
    monkeypatch.setattr(db_client._transport.app.state.settings, "admin_url", URL)  # type: ignore[attr-defined]


def _browser(db_client: AsyncClient) -> AsyncClient:
    """Another browser: same app, its own cookies."""
    return AsyncClient(
        transport=db_client._transport, base_url=db_client.base_url, headers={"X-Requested-With": "dotrix-admin"}
    )


def _invite_token(outbox: OutboxEmailSender, to: str) -> str:
    for message in reversed(outbox.messages):
        if message.to == to:
            match = re.search(r"#/accept\?(\S+)", message.body)
            assert match, message.body
            return parse_qs(match.group(1))["token"][0]
    raise AssertionError("no invite email")


async def _invite_and_accept(
    db_client: AsyncClient, outbox: OutboxEmailSender, email: str, role: str = "viewer", name: str = "Vi"
) -> AsyncClient:
    """The owner (signed in on `db_client`) invites; returns a client signed in as the invitee."""
    res = await db_client.post("/v1/admin/admins/invites", json={"email": email, "role": role})
    assert res.status_code == 201, res.text
    other = _browser(db_client)
    accepted = await other.post(
        "/v1/admin/invites/accept", json={"token": _invite_token(outbox, email), "name": name, "password": PASSWORD}
    )
    assert accepted.status_code == 204, accepted.text
    return other


async def _owner(db_client: AsyncClient) -> None:
    await _admin(db_client)


async def test_invite_emails_the_link_and_the_response_has_no_token(
    db_client: AsyncClient, outbox: OutboxEmailSender
) -> None:
    await _owner(db_client)
    res = await db_client.post("/v1/admin/admins/invites", json={"email": "Vi@Example.com", "role": "viewer"})
    assert res.status_code == 201
    token = _invite_token(outbox, "vi@example.com")
    assert token not in res.text
    body = res.json()
    assert body["emailed"] is True and body["link_path"] is None and body["email"] == "vi@example.com"
    assert f"{URL}/#/accept?token=" in outbox.messages[-1].body
    assert token not in (await db_client.get("/v1/admin/admins/invites")).text


async def test_without_an_admin_url_the_owner_gets_the_link_to_pass_on(
    db_client: AsyncClient, outbox: OutboxEmailSender, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(db_client._transport.app.state.settings, "admin_url", None)  # type: ignore[attr-defined]
    await _owner(db_client)
    res = (await db_client.post("/v1/admin/admins/invites", json={"email": "vi@example.com", "role": "viewer"})).json()
    assert not outbox.messages and res["emailed"] is False and res["note"]
    token = parse_qs(res["link_path"].split("?", 1)[1])["token"][0]
    other = _browser(db_client)
    assert (await other.post("/v1/admin/invites/preview", json={"token": token})).status_code == 200


async def test_accepting_an_invite_creates_the_admin_and_signs_them_in(
    db_client: AsyncClient, outbox: OutboxEmailSender
) -> None:
    await _owner(db_client)
    token_res = await db_client.post("/v1/admin/admins/invites", json={"email": "vi@example.com", "role": "viewer"})
    assert token_res.status_code == 201
    token = _invite_token(outbox, "vi@example.com")
    other = _browser(db_client)
    preview = await other.post("/v1/admin/invites/preview", json={"token": token})
    assert preview.json() == {"email": "vi@example.com", "role": "viewer"}
    assert (await other.post("/v1/admin/invites/accept", json={"token": token, "name": "Vi", "password": PASSWORD})).status_code == 204
    me = (await other.get("/v1/admin/me")).json()
    assert me["email"] == "vi@example.com" and me["role"] == "viewer"
    # Used once: neither preview nor a second accept works, and nothing is pending.
    assert (await _browser(db_client).post("/v1/admin/invites/preview", json={"token": token})).status_code == 400
    again = await _browser(db_client).post(
        "/v1/admin/invites/accept", json={"token": token, "name": "Vi", "password": PASSWORD}
    )
    assert again.status_code == 400
    assert (await db_client.get("/v1/admin/admins/invites")).json() == []
    # The new admin signs in with their own password.
    login = await _browser(db_client).post("/v1/admin/login", json={"email": "vi@example.com", "password": PASSWORD})
    assert login.status_code == 204


async def test_unknown_expired_and_revoked_invites_are_refused(
    db_client: AsyncClient, db_session: AsyncSession, outbox: OutboxEmailSender
) -> None:
    await _owner(db_client)
    anon = _browser(db_client)
    assert (await anon.post("/v1/admin/invites/preview", json={"token": "x" * 30})).status_code == 400

    await db_client.post("/v1/admin/admins/invites", json={"email": "old@example.com", "role": "viewer"})
    expired = _invite_token(outbox, "old@example.com")
    await db_session.execute(
        update(AdminInvite).where(AdminInvite.email == "old@example.com").values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    assert (await anon.post("/v1/admin/invites/preview", json={"token": expired})).status_code == 400
    accept = {"token": expired, "name": "Old", "password": PASSWORD}
    assert (await anon.post("/v1/admin/invites/accept", json=accept)).status_code == 400

    created = (await db_client.post("/v1/admin/admins/invites", json={"email": "gone@example.com", "role": "viewer"})).json()
    revoked = _invite_token(outbox, "gone@example.com")
    assert (await db_client.delete(f"/v1/admin/admins/invites/{created['id']}")).status_code == 204
    assert (await anon.post("/v1/admin/invites/accept", json={**accept, "token": revoked})).status_code == 400
    assert (await db_client.get("/v1/admin/admins/invites")).json() == []


async def test_a_new_invite_revokes_the_earlier_one_and_existing_admins_conflict(
    db_client: AsyncClient, outbox: OutboxEmailSender
) -> None:
    await _owner(db_client)
    await db_client.post("/v1/admin/admins/invites", json={"email": "vi@example.com", "role": "viewer"})
    first = _invite_token(outbox, "vi@example.com")
    await db_client.post("/v1/admin/admins/invites", json={"email": "vi@example.com", "role": "owner"})
    second = _invite_token(outbox, "vi@example.com")
    assert first != second
    anon = _browser(db_client)
    assert (await anon.post("/v1/admin/invites/preview", json={"token": first})).status_code == 400
    assert (await anon.post("/v1/admin/invites/preview", json={"token": second})).json()["role"] == "owner"
    assert len((await db_client.get("/v1/admin/admins/invites")).json()) == 1
    taken = await db_client.post("/v1/admin/admins/invites", json={"email": ADMIN["email"], "role": "viewer"})
    assert taken.status_code == 409


async def test_the_list_shows_roles_and_last_sign_in(db_client: AsyncClient, outbox: OutboxEmailSender) -> None:
    await _owner(db_client)
    await _invite_and_accept(db_client, outbox, "vi@example.com")
    admins = (await db_client.get("/v1/admin/admins")).json()
    assert [(a["email"], a["role"]) for a in admins] == [("admin@example.com", "owner"), ("vi@example.com", "viewer")]
    assert all(a["last_sign_in_at"] and a["disabled_at"] is None for a in admins)


async def test_a_viewer_reads_but_cannot_manage(db_client: AsyncClient, outbox: OutboxEmailSender) -> None:
    await _owner(db_client)
    viewer = await _invite_and_accept(db_client, outbox, "vi@example.com")
    owner_id = (await db_client.get("/v1/admin/me")).json()["id"]
    assert (await viewer.get(HEALTH)).status_code == 200
    assert (await viewer.get("/v1/admin/audit")).status_code == 200
    forbidden = [
        await viewer.get("/v1/admin/admins"),
        await viewer.post("/v1/admin/admins/invites", json={"email": "x@example.com", "role": "viewer"}),
        await viewer.get("/v1/admin/admins/invites"),
        await viewer.delete(f"/v1/admin/admins/invites/{owner_id}"),
        await viewer.patch(f"/v1/admin/admins/{owner_id}", json={"disabled": True}),
        await viewer.delete(f"/v1/admin/admins/{owner_id}"),
        await viewer.put("/v1/admin/storage-limit", json={"workspace_id": owner_id, "storage_limit_mb": 1}),
    ]
    assert [r.status_code for r in forbidden] == [403] * len(forbidden)


async def test_disabling_signs_the_admin_out_and_enabling_lets_them_back(
    db_client: AsyncClient, outbox: OutboxEmailSender
) -> None:
    await _owner(db_client)
    viewer = await _invite_and_accept(db_client, outbox, "vi@example.com")
    assert (await viewer.get(HEALTH)).status_code == 200
    viewer_id = (await viewer.get("/v1/admin/me")).json()["id"]

    res = await db_client.patch(f"/v1/admin/admins/{viewer_id}", json={"disabled": True})
    assert res.status_code == 200 and res.json()["disabled_at"]
    assert (await viewer.get(HEALTH)).status_code == 401
    assert (await viewer.post("/v1/admin/refresh")).status_code == 401
    login = {"email": "vi@example.com", "password": PASSWORD}
    assert (await _browser(db_client).post("/v1/admin/login", json=login)).status_code == 401

    assert (await db_client.patch(f"/v1/admin/admins/{viewer_id}", json={"disabled": False})).json()["disabled_at"] is None
    assert (await _browser(db_client).post("/v1/admin/login", json=login)).status_code == 204


async def test_changing_a_role_takes_effect(db_client: AsyncClient, outbox: OutboxEmailSender) -> None:
    await _owner(db_client)
    viewer = await _invite_and_accept(db_client, outbox, "vi@example.com")
    viewer_id = (await viewer.get("/v1/admin/me")).json()["id"]
    assert (await viewer.get("/v1/admin/admins")).status_code == 403
    assert (await db_client.patch(f"/v1/admin/admins/{viewer_id}", json={"role": "owner"})).json()["role"] == "owner"
    assert (await viewer.get("/v1/admin/admins")).status_code == 200
    assert (await db_client.patch("/v1/admin/admins/" + viewer_id, json={"role": "nope"})).status_code == 422


async def test_removing_an_admin_ends_their_sessions(
    db_client: AsyncClient, db_session: AsyncSession, outbox: OutboxEmailSender
) -> None:
    await _owner(db_client)
    viewer = await _invite_and_accept(db_client, outbox, "vi@example.com")
    viewer_id = (await viewer.get("/v1/admin/me")).json()["id"]
    assert (await db_client.delete(f"/v1/admin/admins/{viewer_id}")).status_code == 204
    assert (await viewer.get(HEALTH)).status_code == 401
    assert await db_session.scalar(select(AdminUser).where(AdminUser.email == "vi@example.com")) is None
    assert (await db_client.delete(f"/v1/admin/admins/{viewer_id}")).status_code == 404
    # Their invite history doesn't block inviting them again.
    assert (await db_client.post("/v1/admin/admins/invites", json={"email": "vi@example.com", "role": "viewer"})).status_code == 201


async def test_the_last_active_owner_is_protected(db_client: AsyncClient, outbox: OutboxEmailSender) -> None:
    await _owner(db_client)
    me = (await db_client.get("/v1/admin/me")).json()["id"]
    for call in (
        db_client.patch(f"/v1/admin/admins/{me}", json={"role": "viewer"}),
        db_client.patch(f"/v1/admin/admins/{me}", json={"disabled": True}),
        db_client.delete(f"/v1/admin/admins/{me}"),
    ):
        res = await call
        assert res.status_code == 409 and "at least one owner" in res.json()["detail"]

    # A second owner makes the first removable; then the second is the last.
    second = await _invite_and_accept(db_client, outbox, "two@example.com", role="owner", name="Two")
    second_id = (await second.get("/v1/admin/me")).json()["id"]
    assert (await db_client.patch(f"/v1/admin/admins/{me}", json={"role": "viewer"})).status_code == 200
    assert (await db_client.get("/v1/admin/admins")).status_code == 403
    assert (await second.patch(f"/v1/admin/admins/{second_id}", json={"disabled": True})).status_code == 409
    assert (await second.delete(f"/v1/admin/admins/{second_id}")).status_code == 409
    # A disabled owner doesn't count as an owner.
    assert (await second.patch(f"/v1/admin/admins/{me}", json={"role": "owner"})).status_code == 200
    assert (await second.patch(f"/v1/admin/admins/{me}", json={"disabled": True})).status_code == 200
    assert (await second.patch(f"/v1/admin/admins/{second_id}", json={"role": "viewer"})).status_code == 409


async def test_passwords_need_twelve_characters(db_client: AsyncClient, outbox: OutboxEmailSender) -> None:
    await _owner(db_client)
    await db_client.post("/v1/admin/admins/invites", json={"email": "vi@example.com", "role": "viewer"})
    token = _invite_token(outbox, "vi@example.com")
    short = await _browser(db_client).post("/v1/admin/invites/accept", json={"token": token, "name": "Vi", "password": "elevenchars"})
    assert short.status_code == 422
    change = await db_client.post("/v1/admin/me/password", json={"current_password": ADMIN["password"], "new_password": "elevenchars"})
    assert change.status_code == 422


async def test_changing_your_password_signs_out_the_others(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _owner(db_client)
    other_browser = _browser(db_client)
    assert (await other_browser.post("/v1/admin/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})).status_code == 204
    assert (await other_browser.get(HEALTH)).status_code == 200

    wrong = await db_client.post("/v1/admin/me/password", json={"current_password": "not the password", "new_password": "a brand new password"})
    assert wrong.status_code == 403
    ok = await db_client.post("/v1/admin/me/password", json={"current_password": ADMIN["password"], "new_password": "a brand new password"})
    assert ok.status_code == 204
    assert (await db_client.get(HEALTH)).status_code == 200  # this session stays
    assert (await other_browser.get(HEALTH)).status_code == 401
    old = await _browser(db_client).post("/v1/admin/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    assert old.status_code == 401
    new = await _browser(db_client).post("/v1/admin/login", json={"email": ADMIN["email"], "password": "a brand new password"})
    assert new.status_code == 204
    admin = await db_session.scalar(select(AdminUser))
    assert admin is not None and admin.password_changed_at is not None


async def test_sign_out_everywhere_else_keeps_this_session(db_client: AsyncClient, db_session: AsyncSession) -> None:
    await _owner(db_client)
    other_browser = _browser(db_client)
    await other_browser.post("/v1/admin/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    assert (await db_client.post("/v1/admin/me/sessions/revoke-others")).status_code == 204
    assert (await db_client.get(HEALTH)).status_code == 200
    assert (await other_browser.get(HEALTH)).status_code == 401
    live = (await db_session.scalars(select(AdminSession).where(AdminSession.revoked_at.is_(None)))).all()
    assert len(live) == 1


async def test_the_storage_limit_is_for_owners(db_client: AsyncClient, outbox: OutboxEmailSender, signup) -> None:
    owner = await signup()
    ws = (await db_client.get("/v1/workspaces", headers=owner.headers)).json()[0]
    await _owner(db_client)
    viewer = await _invite_and_accept(db_client, outbox, "vi@example.com")
    body = {"workspace_id": ws["id"], "storage_limit_mb": 5}
    assert (await viewer.put("/v1/admin/storage-limit", json=body)).status_code == 403
    assert (await db_client.put("/v1/admin/storage-limit", json=body)).status_code == 204
