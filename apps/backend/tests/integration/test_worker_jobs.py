"""Background jobs through Redis: emails and password-reset requests queued by the API and
done by the worker, retries, and rate limits shared through Redis. Needs Redis (skipped
if unreachable)."""
import uuid
from typing import Any

from arq.worker import Worker
from httpx import AsyncClient

from dotrix_backend.core.email import EmailMessage, OutboxEmailSender
from dotrix_backend.core.jobs import JobContext, QueuedEmailSender, QueuedJobs
from dotrix_backend.core.ratelimit import Limit, RedisRateLimiter
from dotrix_backend.jobs import JOBS
from dotrix_backend.worker import job_function


def _worker(redis: Any, queue: str, ctx: JobContext, jobs: dict[str, Any] = JOBS) -> Worker:
    return Worker(
        functions=[job_function(name, job, backoff_seconds=0) for name, job in jobs.items()],
        queue_name=queue,
        redis_pool=redis,
        burst=True,
        handle_signals=False,
        poll_delay=0.05,
        max_jobs=1,  # jobs here share the test's one connection: one at a time
        ctx={"jobs": ctx},
    )


def _context(db_client: AsyncClient, outbox: OutboxEmailSender) -> JobContext:
    app = db_client._transport.app  # type: ignore[attr-defined]
    return JobContext(app.state.runner.session_factory, app.state.settings, outbox)


async def test_the_worker_sends_queued_emails(redis, db_client: AsyncClient, outbox: OutboxEmailSender) -> None:
    queue = f"dotrix:test:{uuid.uuid4().hex[:8]}"
    sender = QueuedEmailSender(QueuedJobs(redis, queue_name=queue))
    await sender.send(EmailMessage(to="ada@example.com", subject="Hi", body="Hello"))
    assert outbox.messages == []  # queued, not sent
    await _worker(redis, queue, _context(db_client, outbox)).main()
    assert outbox.messages == [EmailMessage(to="ada@example.com", subject="Hi", body="Hello")]


async def test_password_reset_requests_are_done_by_the_worker(
    redis, db_client: AsyncClient, signup, outbox: OutboxEmailSender, email_token
) -> None:
    ada = await signup()
    outbox.messages.clear()
    queue = f"dotrix:test:{uuid.uuid4().hex[:8]}"
    db_client._transport.app.state.jobs = QueuedJobs(redis, queue_name=queue)  # type: ignore[attr-defined]
    for email in (ada.email, "nobody@example.com"):
        assert (await db_client.post("/v1/auth/password-reset/request", json={"email": email})).status_code == 202
    assert outbox.messages == []

    await _worker(redis, queue, _context(db_client, outbox)).main()
    assert [m.to for m in outbox.messages] == [ada.email]  # nothing for the unknown address
    reset = await db_client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": email_token("/reset-password"), "new_password": "a brand new password"},
    )
    assert reset.status_code == 204


async def test_a_failing_job_is_retried(redis, db_client: AsyncClient, outbox: OutboxEmailSender) -> None:
    attempts: list[str] = []

    async def flaky(ctx: JobContext, *, to: str) -> None:
        attempts.append(to)
        if len(attempts) < 3:
            raise ConnectionError("provider unavailable")
        await ctx.email.send(EmailMessage(to=to, subject="s", body="b"))

    queue = f"dotrix:test:{uuid.uuid4().hex[:8]}"
    await QueuedJobs(redis, queue_name=queue).enqueue("flaky", to="ada@example.com")
    await _worker(redis, queue, _context(db_client, outbox), {"flaky": flaky}).main()
    assert len(attempts) == 3 and [m.to for m in outbox.messages] == ["ada@example.com"]


async def test_redis_rate_limits_are_shared_between_api_processes(redis) -> None:
    prefix = f"dotrix:test:{uuid.uuid4().hex[:8]}"
    limit = Limit("login:email", 3, 60)
    one, two = RedisRateLimiter(redis, prefix=prefix), RedisRateLimiter(redis, prefix=prefix)
    assert [await one.hit(limit, "a"), await two.hit(limit, "a"), await one.hit(limit, "a")] == [None] * 3
    wait = await two.hit(limit, "a")
    assert wait is not None and 1 <= wait <= 120
    assert await two.hit(limit, "b") is None
