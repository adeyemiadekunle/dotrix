"""Operator alerts: the conditions (pure), then the job that opens, emails once and clears them."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.email import EmailMessage, EmailSendError, OutboxEmailSender
from dotrix_backend.core.jobs import JobContext
from dotrix_backend.jobs import check_operator_alerts
from dotrix_backend.modules.admin.alerts import conditions, evaluate
from dotrix_backend.modules.admin.models import AdminAlert, AdminUser
from dotrix_backend.modules.admin.schemas import DependencyCheck, PlatformHealth, StuckRun
from dotrix_backend.modules.agents.models import RunStatus

from .test_observe import _chat_run

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def health(**kw) -> PlatformHealth:
    base = dict(
        generated_at=NOW, version="0", environment="test", jobs="worker", sandbox="docker", database_ms=1.0,
        queue_pending=0, queue_oldest_seconds=None, queue_discarded_24h=0, worker_last_took_at=None, runs_running=0,
        runs_queued=0, stuck=[], recovery_required=0, interrupted=0, sandboxes_warm=0, sandboxes_asleep=0,
        runners_online=0, runners=0, failed_24h=0, finished_24h=0, workers_alive=1,
        dependencies=[DependencyCheck(id=i, state="ok", detail="ok") for i in ("redis", "workers", "storage")]
        + [DependencyCheck(id="email", state="degraded", detail="Console"), DependencyCheck(id="github", state="off", detail="off")],
    )
    return PlatformHealth(**{**base, **kw})


def stuck(minutes: int) -> StuckRun:
    return StuckRun(kind="chat", id=uuid.uuid4(), status="running", workspace="ws", lease_expired_at=NOW - timedelta(minutes=minutes))


def test_a_healthy_deployment_has_no_conditions() -> None:
    assert conditions(health(), NOW) == {}
    assert conditions(health(stuck=[stuck(5)], queue_pending=3, queue_oldest_seconds=60, failed_24h=9, finished_24h=9), NOW) == {}


@pytest.mark.parametrize(
    ("kw", "key"),
    [
        ({"dependencies": [DependencyCheck(id="redis", state="down", detail="x")]}, "dependency:redis"),
        ({"dependencies": [DependencyCheck(id="storage", state="down", detail="x")]}, "dependency:storage"),
        ({"workers_alive": 0}, "workers"),
        ({"stuck": [stuck(11)]}, "stuck_runs"),
        ({"queue_pending": 2, "queue_oldest_seconds": 601}, "queue_stalled"),
        ({"recovery_required": 1}, "recovery_required"),
        ({"failed_24h": 6, "finished_24h": 10}, "failure_rate"),
        ({"notification_emails_waiting": 4, "notification_email_oldest_seconds": 3601}, "emails_waiting"),
    ],
)
def test_each_condition_fires(kw: dict, key: str) -> None:
    found = conditions(health(**kw), NOW)
    assert set(found) == {key}
    assert 0 < len(found[key]) <= 300


def test_edges_and_modes_do_not_fire() -> None:
    assert conditions(health(failed_24h=5, finished_24h=10), NOW) == {}  # half is not more than half
    assert conditions(health(failed_24h=9, finished_24h=9), NOW) == {}  # too few runs
    assert conditions(health(jobs="local", workers_alive=None), NOW) == {}
    assert conditions(health(queue_pending=0, queue_oldest_seconds=900), NOW) == {}
    # A workers dependency that is down is the `workers` condition's business, not a second alert.
    down = [DependencyCheck(id="workers", state="down", detail="x")]
    assert conditions(health(dependencies=down, workers_alive=0), NOW) == {"workers": "No worker has checked in recently"}


@pytest.fixture
def sent(outbox: OutboxEmailSender):
    """The operator alert emails so far (sign-ups in a test send others)."""
    return lambda: [m for m in outbox.messages if m.subject.startswith("dotrix: ")]


@pytest.fixture
def ctx_for(db_client: AsyncClient, outbox: OutboxEmailSender, monkeypatch: pytest.MonkeyPatch):
    app = db_client._transport.app  # type: ignore[attr-defined]

    def make(emails: list[str] | None = None, email=None) -> JobContext:
        monkeypatch.setattr(app.state.settings, "alert_emails", emails if emails is not None else ["ops@example.com"])
        return JobContext(app.state.runner.session_factory, app.state.settings, email or outbox)

    return make


async def _stuck_run(db_client: AsyncClient, db_session: AsyncSession, signup, name: str = "Zebra Secret Holdings"):
    ada = await signup()
    ws = (await db_client.post("/v1/workspaces", json={"name": name, "kind": "organisation"}, headers=ada.headers))
    if ws.status_code != 201:
        ws = None
        ws_id = (await db_client.get("/v1/workspaces", headers=ada.headers)).json()[0]["id"]
    else:
        ws_id = ws.json()["id"]
    project = (await db_client.post(f"/v1/workspaces/{ws_id}/projects", json={"key": "KUN", "name": "Secret Kunemi"}, headers=ada.headers)).json()
    run = _chat_run(ws_id, project["id"], ada, status=RunStatus.RUNNING, lease_expires_at=datetime.now(UTC) - timedelta(minutes=30))
    db_session.add(run)
    await db_session.commit()
    return run


async def test_a_healthy_deployment_sends_nothing(ctx_for, sent, db_session: AsyncSession) -> None:
    ctx = ctx_for()
    for _ in range(3):
        assert (await evaluate(ctx))["open"] == 0
    assert sent() == []
    assert (await db_session.scalars(select(AdminAlert))).all() == []


async def test_a_condition_is_emailed_on_its_second_check_once_and_again_when_it_clears(
    ctx_for, sent, db_client, db_session: AsyncSession, signup
) -> None:
    ctx = ctx_for()
    run = await _stuck_run(db_client, db_session, signup)

    first = await evaluate(ctx)
    assert first["open"] == 1 and sent() == []  # opened, nobody paged by a blip
    second = await evaluate(ctx)
    assert second["opened"] == 1 and len(sent()) == 1
    mail = sent()[0]
    assert mail.to == "ops@example.com" and "1 run stuck" in mail.body
    third = await evaluate(ctx)
    assert third["open"] == 1 and len(sent()) == 1  # no change: no email

    # What people wrote and named never reaches the email.
    for secret in ("Zebra Secret", "Secret Kunemi", "hello", str(run.id)):
        assert secret not in mail.body and secret not in mail.subject

    run.lease_expires_at = datetime.now(UTC)  # the sweep picked it up
    await db_session.commit()
    cleared = await evaluate(ctx)
    assert cleared["open"] == 0 and cleared["cleared"] == 1 and len(sent()) == 2
    assert "Cleared" in sent()[1].body and sent()[1].subject.endswith("1 cleared")
    await evaluate(ctx)
    assert len(sent()) == 2
    row = (await db_session.scalars(select(AdminAlert))).one()
    await db_session.refresh(row)
    assert row.resolved_at is not None and row.notified_at is not None and row.clear_notified_at is not None


async def test_a_blip_is_never_emailed(ctx_for, sent, db_client, db_session: AsyncSession, signup) -> None:
    ctx = ctx_for()
    run = await _stuck_run(db_client, db_session, signup)
    await evaluate(ctx)
    run.lease_expires_at = datetime.now(UTC)
    await db_session.commit()
    await evaluate(ctx)
    await evaluate(ctx)
    assert sent() == []
    row = (await db_session.scalars(select(AdminAlert))).one()
    await db_session.refresh(row)
    assert row.resolved_at is not None and row.notified_at is None


async def test_without_recipients_nothing_is_sent_and_nothing_fails(
    ctx_for, sent, db_client, db_session: AsyncSession, signup
) -> None:
    ctx = ctx_for([])
    await _stuck_run(db_client, db_session, signup)
    await evaluate(ctx)
    assert (await evaluate(ctx))["emails"] == 0
    assert sent() == []


async def test_without_a_list_the_active_owner_admins_are_emailed(
    ctx_for, sent, db_client, db_session: AsyncSession, signup
) -> None:
    ctx = ctx_for([])
    now = datetime.now(UTC)
    db_session.add_all(
        [
            AdminUser(email="owner@example.com", name="O", password_hash="x", created_at=now, role="owner"),
            AdminUser(email="gone@example.com", name="G", password_hash="x", created_at=now, role="owner", disabled_at=now),
            AdminUser(email="viewer@example.com", name="V", password_hash="x", created_at=now, role="viewer"),
        ]
    )
    await db_session.commit()
    await _stuck_run(db_client, db_session, signup)
    await evaluate(ctx)
    await evaluate(ctx)
    assert [m.to for m in sent()] == ["owner@example.com"]


async def test_an_email_outage_keeps_the_alert_unnotified_and_the_job_alive(
    ctx_for, sent, db_client, db_session: AsyncSession, signup
) -> None:
    class Down:
        async def send(self, message: EmailMessage) -> None:
            raise EmailSendError(503, "provider said secret-key-123", retryable=True)

    run = await _stuck_run(db_client, db_session, signup)
    await evaluate(ctx_for(email=Down()))
    out = await evaluate(ctx_for(email=Down()))
    assert out["emails"] == 0
    row = (await db_session.scalars(select(AdminAlert))).one()
    await db_session.refresh(row)
    assert row.notified_at is None
    await evaluate(ctx_for())  # the provider is back: tried again
    assert len(sent()) == 1 and "secret-key" not in sent()[0].body
    assert run.id


async def test_an_alert_is_sent_again_until_every_recipient_has_it(
    ctx_for, sent, db_client, db_session: AsyncSession, signup, outbox
) -> None:
    class OneDown:
        def __init__(self) -> None:
            self.down = True

        async def send(self, message: EmailMessage) -> None:
            if self.down and message.to == "b@example.com":
                raise EmailSendError(503, "provider busy", retryable=True)
            await outbox.send(message)

    mail = OneDown()
    await _stuck_run(db_client, db_session, signup)
    ctx = ctx_for(["a@example.com", "b@example.com"], email=mail)
    await evaluate(ctx)
    await evaluate(ctx)  # a@ got it, b@ didn't
    assert [m.to for m in sent()] == ["a@example.com"]
    row = (await db_session.scalars(select(AdminAlert))).one()
    await db_session.refresh(row)
    assert row.notified_at is None
    mail.down = False
    await evaluate(ctx)  # the same message to both: the provider drops a@'s copy by its content
    assert [m.to for m in sent()] == ["a@example.com", "a@example.com", "b@example.com"]
    assert sent()[0].body == sent()[1].body
    await db_session.refresh(row)
    assert row.notified_at is not None


async def test_the_same_outage_again_is_a_new_email(ctx_for, sent, db_client, db_session: AsyncSession, signup) -> None:
    ctx = ctx_for()
    run = await _stuck_run(db_client, db_session, signup)
    await evaluate(ctx)
    await evaluate(ctx)
    run.lease_expires_at = datetime.now(UTC)
    await db_session.commit()
    await evaluate(ctx)  # cleared
    run.lease_expires_at = datetime.now(UTC) - timedelta(minutes=30)
    await db_session.commit()
    await evaluate(ctx, now=datetime.now(UTC) + timedelta(minutes=1))
    await evaluate(ctx, now=datetime.now(UTC) + timedelta(minutes=2))
    opened = [m for m in sent() if "Needs attention" in m.body]
    assert len(opened) == 2 and opened[0].subject == opened[1].subject
    assert opened[0].body != opened[1].body  # each says when it started, so the provider sends both


async def test_the_registered_job_runs_and_the_console_lists_alerts(
    ctx_for, sent, db_client: AsyncClient, db_session: AsyncSession, signup
) -> None:
    ctx = ctx_for()
    await _stuck_run(db_client, db_session, signup)
    await check_operator_alerts(ctx)
    await check_operator_alerts(ctx)
    assert len(sent()) == 1

    db_client.headers["X-Requested-With"] = "dotrix-admin"
    res = await db_client.post("/v1/admin/signup", json={"email": "admin@example.com", "name": "Admin", "password": "admin secret 123"})
    assert res.status_code == 201
    listed = (await db_client.get("/v1/admin/observe/alerts")).json()
    assert [a["key"] for a in listed["open"]] == ["stuck_runs"] and listed["open"][0]["notified"] is True
    assert listed["resolved"] == []
    assert "Zebra" not in str(listed)


def test_alert_emails_accept_a_comma_list_or_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from dotrix_backend.core.settings import Settings

    # Settings read the whole environment: give it the one required value CI doesn't set.
    monkeypatch.setenv("DOTRIX_JWT_SECRET", "test-secret-for-settings-parsing-only-0123456789")
    monkeypatch.setenv("DOTRIX_ALERT_EMAILS", "a@x.com, b@x.com")
    assert Settings().alert_emails == ["a@x.com", "b@x.com"]
    monkeypatch.setenv("DOTRIX_ALERT_EMAILS", '["c@x.com"]')
    assert Settings().alert_emails == ["c@x.com"]
