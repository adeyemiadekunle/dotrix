"""Admin sign-in with an authenticator app: enrolment, the two-step sign-in, recovery codes and the way out."""
import time
from types import SimpleNamespace

import jwt
import pyotp
import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.crypto import Secrets
from dotrix_backend.modules.admin import service as admin_service
from dotrix_backend.modules.admin.accounts import create_admin, reset_admin_two_factor
from dotrix_backend.modules.admin.models import AdminRecoveryCode, AdminSession, AdminUser

from .test_admin import ADMIN, _admin

HEALTH = "/v1/admin/observe/health"
ME = "/v1/admin/me"
LOGIN = {"email": ADMIN["email"], "password": ADMIN["password"]}


_skew = [0]


def code_for(secret: str) -> str:
    """The authenticator's code now, on the clock the server sees."""
    return pyotp.TOTP(secret).at(time.time() + _skew[0])


def next_step() -> None:
    """Thirty seconds pass: a code is accepted once per step, so a test that needs another moves on."""
    _skew[0] += 30


@pytest.fixture(autouse=True)
def encryption(db_client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The server can store a TOTP secret, so enrolment is required. Its clock is ours to move."""
    _skew[0] = 0
    monkeypatch.setattr(
        admin_service, "time", SimpleNamespace(time=lambda: time.time() + _skew[0])
    )
    db_client.headers["X-Requested-With"] = "dotrix-admin"
    db_client._transport.app.state.secrets = Secrets(Fernet.generate_key().decode())  # type: ignore[attr-defined]


def _browser(db_client: AsyncClient) -> AsyncClient:
    return AsyncClient(
        transport=db_client._transport, base_url=db_client.base_url, headers={"X-Requested-With": "dotrix-admin"}
    )


async def enrol(client: AsyncClient) -> tuple[str, list[str]]:
    """Set up the signed-in admin's authenticator; returns the secret and the recovery codes."""
    started = await client.post("/v1/admin/me/two-factor/start")
    assert started.status_code == 200, started.text
    secret = started.json()["secret"]
    assert started.json()["otpauth_uri"].startswith("otpauth://totp/")
    confirmed = await client.post("/v1/admin/me/two-factor/confirm", json={"code": code_for(secret)})
    assert confirmed.status_code == 200, confirmed.text
    return secret, confirmed.json()["recovery_codes"]


async def _enrolled(db_client: AsyncClient) -> tuple[str, list[str]]:
    await _admin(db_client)
    return await enrol(db_client)


async def _challenge(client: AsyncClient) -> str:
    res = await client.post("/v1/admin/login", json=LOGIN)
    assert res.status_code == 200, res.text
    assert res.json()["second_factor"] == "totp"
    assert not res.cookies.get("dtx_admin_access") and not res.cookies.get("dtx_admin_refresh")
    return res.json()["challenge"]


async def test_a_new_admin_must_enrol_before_anything_else(db_client: AsyncClient) -> None:
    await _admin(db_client)
    me = (await db_client.get(ME)).json()
    assert me["must_enrol"] is True and me["two_factor"] is False
    res = await db_client.get(HEALTH)
    assert res.status_code == 403 and "two-factor" in res.text
    assert (await db_client.get("/v1/admin/admins")).status_code == 403

    _, codes = await enrol(db_client)
    assert len(codes) == 10 and len(set(codes)) == 10
    me = (await db_client.get(ME)).json()
    assert me["must_enrol"] is False and me["two_factor"] is True
    assert (await db_client.get(HEALTH)).status_code == 200


async def test_the_secret_is_stored_encrypted_and_codes_hashed(db_client: AsyncClient, db_session: AsyncSession) -> None:
    secret, codes = await _enrolled(db_client)
    admin = (await db_session.scalars(select(AdminUser))).one()
    assert admin.totp_secret_encrypted and secret not in admin.totp_secret_encrypted
    stored = {c.code_hash for c in (await db_session.scalars(select(AdminRecoveryCode))).all()}
    assert len(stored) == 10 and not stored & set(codes)


async def test_confirming_with_a_wrong_code_or_before_starting_is_refused(db_client: AsyncClient) -> None:
    await _admin(db_client)
    assert (await db_client.post("/v1/admin/me/two-factor/confirm", json={"code": "123456"})).status_code == 422
    secret = (await db_client.post("/v1/admin/me/two-factor/start")).json()["secret"]
    wrong = "000000" if code_for(secret) != "000000" else "111111"
    assert (await db_client.post("/v1/admin/me/two-factor/confirm", json={"code": wrong})).status_code == 401
    assert (await db_client.get(HEALTH)).status_code == 403


async def test_sign_in_needs_the_code_after_the_password(db_client: AsyncClient) -> None:
    secret, _ = await _enrolled(db_client)
    next_step()
    other = _browser(db_client)
    challenge = await _challenge(other)
    assert (await other.get(ME)).status_code == 401  # login alone is no session

    res = await other.post("/v1/admin/login/verify", json={"challenge": challenge, "code": code_for(secret)})
    assert res.status_code == 204, res.text
    assert res.cookies.get("dtx_admin_access") and res.cookies.get("dtx_admin_refresh")
    assert (await other.get(HEALTH)).status_code == 200


async def test_a_wrong_code_is_refused_and_a_wrong_password_gets_no_challenge(db_client: AsyncClient) -> None:
    secret, _ = await _enrolled(db_client)
    next_step()
    other = _browser(db_client)
    challenge = await _challenge(other)
    wrong = "000000" if code_for(secret) != "000000" else "111111"
    res = await other.post("/v1/admin/login/verify", json={"challenge": challenge, "code": wrong})
    assert res.status_code == 401 and "That code didn't work" in res.text and not res.cookies.get("dtx_admin_access")
    assert (await other.post("/v1/admin/login", json={**LOGIN, "password": "not the password"})).status_code == 401


async def test_a_code_works_once(db_client: AsyncClient) -> None:
    secret, _ = await _enrolled(db_client)
    # Confirming used the current step, so the same code can't open a session now.
    code = code_for(secret)
    other = _browser(db_client)
    res = await other.post("/v1/admin/login/verify", json={"challenge": await _challenge(other), "code": code})
    assert res.status_code == 401
    # The next step's code is fine, once.
    next_step()
    later = code_for(secret)
    first = await other.post("/v1/admin/login/verify", json={"challenge": await _challenge(other), "code": later})
    assert first.status_code == 204
    again = _browser(db_client)
    assert (await again.post("/v1/admin/login/verify", json={"challenge": await _challenge(again), "code": later})).status_code == 401


async def test_a_recovery_code_works_once(db_client: AsyncClient) -> None:
    _, codes = await _enrolled(db_client)
    other = _browser(db_client)
    res = await other.post("/v1/admin/login/verify", json={"challenge": await _challenge(other), "code": codes[0]})
    assert res.status_code == 204 and other.cookies.get("dtx_admin_access")
    again = _browser(db_client)
    res = await again.post("/v1/admin/login/verify", json={"challenge": await _challenge(again), "code": codes[0]})
    assert res.status_code == 401
    third = _browser(db_client)
    res = await third.post("/v1/admin/login/verify", json={"challenge": await _challenge(third), "code": codes[1]})
    assert res.status_code == 204


async def test_the_challenge_is_not_a_session_and_expires(db_client: AsyncClient) -> None:
    secret, _ = await _enrolled(db_client)
    other = _browser(db_client)
    challenge = await _challenge(other)
    for path in (ME, HEALTH):
        res = await other.get(path, headers={"Cookie": f"dtx_admin_access={challenge}"})
        assert res.status_code == 401
    # An access token is not a challenge either.
    access = db_client.cookies.get("dtx_admin_access")
    assert access
    res = await other.post("/v1/admin/login/verify", json={"challenge": access, "code": code_for(secret)})
    assert res.status_code == 401
    # An expired challenge is refused.
    settings = db_client._transport.app.state.settings  # type: ignore[attr-defined]
    claims = jwt.decode(challenge, settings.jwt_secret.get_secret_value(), algorithms=["HS256"], issuer=settings.jwt_issuer)
    claims["exp"] = int(time.time()) - 10
    expired = jwt.encode(claims, settings.jwt_secret.get_secret_value(), algorithm="HS256")
    next_step()
    res = await other.post("/v1/admin/login/verify", json={"challenge": expired, "code": code_for(secret)})
    assert res.status_code == 401


async def test_replacing_recovery_codes_needs_a_current_code(db_client: AsyncClient) -> None:
    secret, old = await _enrolled(db_client)
    url = "/v1/admin/me/two-factor/recovery-codes"
    assert (await db_client.post(url, json={"code": "000000"})).status_code == 401
    # Confirming spent this step; the next one is accepted.
    next_step()
    res = await db_client.post(url, json={"code": code_for(secret)})
    assert res.status_code == 200
    new = res.json()["recovery_codes"]
    assert len(new) == 10 and not set(new) & set(old)
    other = _browser(db_client)
    res = await other.post("/v1/admin/login/verify", json={"challenge": await _challenge(other), "code": old[0]})
    assert res.status_code == 401


async def test_starting_again_after_enrolment_is_a_conflict(db_client: AsyncClient) -> None:
    await _enrolled(db_client)
    assert (await db_client.post("/v1/admin/me/two-factor/start")).status_code == 409


async def test_reset_puts_the_admin_back_to_must_enrol_and_signs_them_out(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enrolled(db_client)
    await reset_admin_two_factor(db_session, email=ADMIN["email"].upper())
    await db_session.commit()
    assert (await db_client.get(ME)).status_code == 401
    assert not (await db_session.scalars(select(AdminRecoveryCode))).all()
    assert all(s.revoked_at for s in (await db_session.scalars(select(AdminSession))).all())

    res = await db_client.post("/v1/admin/login", json=LOGIN)
    assert res.status_code == 204  # no second factor now: a session that may only enrol
    assert (await db_client.get(ME)).json()["must_enrol"] is True
    assert (await db_client.get(HEALTH)).status_code == 403


async def test_an_owner_resets_another_admins_second_factor_but_not_their_own(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _enrolled(db_client)
    viewer = await create_admin(db_session, email="vi@example.com", name="Vi", password="a long enough secret", role="viewer")
    await db_session.commit()
    other = _browser(db_client)
    await other.post("/v1/admin/login", json={"email": "vi@example.com", "password": "a long enough secret"})
    await enrol(other)
    listed = {a["email"]: a for a in (await db_client.get("/v1/admin/admins")).json()}
    assert listed["vi@example.com"]["two_factor"] is True

    me = (await db_client.get(ME)).json()
    assert (await db_client.post(f"/v1/admin/admins/{me['id']}/two-factor/reset")).status_code == 409
    assert (await other.post(f"/v1/admin/admins/{me['id']}/two-factor/reset")).status_code == 403  # a viewer

    assert (await db_client.post(f"/v1/admin/admins/{viewer.id}/two-factor/reset")).status_code == 204
    assert (await other.get(ME)).status_code == 401
    assert (await db_client.get("/v1/admin/admins")).json()[1]["two_factor"] is False
    assert (await db_client.post(f"/v1/admin/admins/{me['id'][:-1]}0/two-factor/reset")).status_code in (404, 409)


async def test_without_an_encryption_key_sign_in_works_as_before(db_client: AsyncClient) -> None:
    db_client._transport.app.state.secrets = Secrets(None)  # type: ignore[attr-defined]
    await _admin(db_client)
    me = (await db_client.get(ME)).json()
    assert me["must_enrol"] is False and me["two_factor"] is False
    assert (await db_client.get(HEALTH)).status_code == 200
    assert (await db_client.post("/v1/admin/me/two-factor/start")).status_code == 503
    other = _browser(db_client)
    assert (await other.post("/v1/admin/login", json=LOGIN)).status_code == 204


async def test_a_session_from_before_enrolment_was_required_must_enrol_too(db_client: AsyncClient) -> None:
    db_client._transport.app.state.secrets = Secrets(None)  # type: ignore[attr-defined]
    await _admin(db_client)
    assert (await db_client.get(HEALTH)).status_code == 200
    db_client._transport.app.state.secrets = Secrets(Fernet.generate_key().decode())  # type: ignore[attr-defined]
    assert (await db_client.get(HEALTH)).status_code == 403


async def test_the_activity_trail_records_two_factor_actions_and_a_sign_in_only_once_complete(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    from dotrix_backend.modules.admin.models import AdminEvent

    async def actions() -> list[str]:
        return list(await db_session.scalars(select(AdminEvent.action).order_by(AdminEvent.created_at, AdminEvent.id)))

    secret, _ = await _enrolled(db_client)
    assert "admin.two_factor_enabled" in await actions()

    browser = _browser(db_client)
    before = len(await actions())
    challenge = await _challenge(browser)
    # The password alone isn't a sign-in: nothing is recorded until the code.
    assert len(await actions()) == before
    bad = await browser.post("/v1/admin/login/verify", json={"challenge": challenge, "code": "000000"})
    assert bad.status_code == 401
    assert (await actions())[-1] == "admin.sign_in_failed"
    next_step()
    ok = await browser.post("/v1/admin/login/verify", json={"challenge": challenge, "code": code_for(secret)})
    assert ok.status_code == 204, ok.text
    assert (await actions())[-1] == "admin.signed_in"

    next_step()
    replaced = await db_client.post("/v1/admin/me/two-factor/recovery-codes", json={"code": code_for(secret)})
    assert replaced.status_code == 200, replaced.text
    assert (await actions())[-1] == "admin.recovery_codes_replaced"

    await reset_admin_two_factor(db_session, email=ADMIN["email"])
    await db_session.commit()
    last = await db_session.scalar(select(AdminEvent).order_by(AdminEvent.created_at.desc(), AdminEvent.id.desc()))
    assert last.action == "admin.two_factor_reset" and last.actor_email == "command line"
    assert last.target_email == ADMIN["email"]
