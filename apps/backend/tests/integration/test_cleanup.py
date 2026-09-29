"""The hourly cleanup deletes rows nothing will use again, and nothing else."""
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core.jobs import JobContext
from pmagent_backend.jobs import cleanup_expired
from pmagent_backend.modules.api_tokens.models import DeviceAuthorization
from pmagent_backend.modules.auth.models import ActionToken, RefreshToken
from pmagent_backend.modules.invites.models import Invite


async def _counts(session: AsyncSession) -> dict[str, int]:
    tables = {"refresh_tokens": RefreshToken, "action_tokens": ActionToken,
              "device_authorizations": DeviceAuthorization, "invites": Invite}
    return {name: await session.scalar(select(func.count()).select_from(model)) for name, model in tables.items()}


async def test_cleanup_deletes_only_what_is_finished(
    db_client: AsyncClient, db_session: AsyncSession, signup, create_team, outbox
) -> None:
    ada = await signup()  # a refresh token (30 days) and an email-verification link (48 hours)
    team = await create_team(ada.headers, in_org=True)
    invite = await db_client.post(
        f"/v1/workspaces/{team['id']}/invites", json={"email": "bob@example.com", "role": "member"}, headers=ada.headers
    )
    assert invite.status_code == 201  # valid 7 days
    device = await db_client.post("/v1/auth/device/code", json={"client_name": "pmagent CLI"})
    assert device.status_code == 200  # valid minutes
    before = await _counts(db_session)
    assert before == {"refresh_tokens": 1, "action_tokens": 1, "device_authorizations": 1, "invites": 1}

    app = db_client._transport.app  # type: ignore[attr-defined]
    ctx = JobContext(app.state.runner.session_factory, app.state.settings, outbox)
    now = datetime.now(UTC)

    # Right away: nothing is old enough.
    assert set((await cleanup_expired(ctx)).values()) == {0}

    # In 10 days: the verification link and the device login are over (and a week past it);
    # the refresh token is still valid, and an expired invite is kept 30 days.
    deleted = await cleanup_expired(ctx, now=(now + timedelta(days=10)).isoformat())
    assert deleted == {"refresh_tokens": 0, "action_tokens": 1, "email_signups": 0, "device_authorizations": 1, "invites": 0}

    # In 40 days: the refresh token expired over a week ago, the invite over 30 days ago.
    deleted = await cleanup_expired(ctx, now=(now + timedelta(days=40)).isoformat())
    assert deleted == {"refresh_tokens": 1, "action_tokens": 0, "email_signups": 0, "device_authorizations": 0, "invites": 1}
    db_session.expire_all()
    assert set((await _counts(db_session)).values()) == {0}


async def test_revoked_refresh_tokens_are_kept_until_they_expire(db_client: AsyncClient, signup, outbox) -> None:
    """A revoked token that comes back still signs its whole session out, so cleanup keeps
    it for as long as it could have been used."""
    ada = await signup()
    rotated = await db_client.post("/v1/auth/refresh", json={"refresh_token": ada.tokens["refresh_token"]})
    assert rotated.status_code == 200
    app = db_client._transport.app  # type: ignore[attr-defined]
    ctx = JobContext(app.state.runner.session_factory, app.state.settings, outbox)
    deleted = await cleanup_expired(ctx, now=(datetime.now(UTC) + timedelta(days=20)).isoformat())
    assert deleted["refresh_tokens"] == 0
    reuse = await db_client.post("/v1/auth/refresh", json={"refresh_token": ada.tokens["refresh_token"]})
    assert "reuse" in reuse.json()["detail"]
