"""A coding session as it changes, for server-sent events.

Kai's events are written to the database by whoever codes the turn (a worker, or a person's own
runner through the API), so the stream reads them from there: a cheap look at the session's turns
a couple of times a second, and the turns in full only when something moved. Every read checks
again that the session is still the reader's to see.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dotrix_backend.core.errors import NotFound
from dotrix_backend.modules.projects.deps import ProjectAccess

from .models import CodingRun, CodingRunStatus
from .schemas import CodingRunRead
from .service import CodingService

POLL_SECONDS = 0.5
PING_SECONDS = 15.0
# Whatever the cheap look misses (a field it doesn't watch) is sent by this time.
REFRESH_SECONDS = 10.0
# A connection ends after this long; the client opens another, and its access is checked afresh.
LIFETIME_SECONDS = 600.0

# Turns that can still change by themselves or wait on a person: the stream stays open for them.
OPEN = frozenset({
    CodingRunStatus.AWAITING_APPROVAL, CodingRunStatus.QUEUED, CodingRunStatus.RUNNING,
    CodingRunStatus.CHANGES_READY,
})


async def follow_session(
    factory: async_sessionmaker[AsyncSession], service: Callable[[AsyncSession], CodingService],
    access: ProjectAccess, session_id: uuid.UUID, *, poll: float = POLL_SECONDS, lifetime: float = LIFETIME_SECONDS,
) -> AsyncIterator[tuple[str, list[CodingRunRead] | None]]:
    """`("turns", turns)` first and whenever the session changed, `("ping", None)` while it's
    quiet, and `("end", None)` once no turn waits or works (or it's no longer the reader's)."""
    seen: tuple[object, ...] | None = None
    started = sent = read = time.monotonic()
    while True:
        async with factory() as session:
            rows = (await session.execute(
                select(CodingRun.id, CodingRun.status, CodingRun.event_count, CodingRun.commit_sha, CodingRun.pr_number,
                       CodingRun.pr_state, CodingRun.ci_state, CodingRun.review_run_id, CodingRun.finished_at)
                .where(CodingRun.project_id == access.project.id, CodingRun.session_id == session_id)
                .order_by(CodingRun.turn)
            )).all()
            mark = tuple(tuple(row) for row in rows)
            now = time.monotonic()
            if mark != seen or now - read >= REFRESH_SECONDS:
                try:
                    turns = await service(session).session_turns(access, session_id)
                except NotFound:
                    yield "end", None
                    return
                seen, sent, read = mark, now, now
                yield "turns", turns
        if not any(row.status in OPEN for row in rows):
            yield "end", None
            return
        if time.monotonic() - started >= lifetime:
            return
        await asyncio.sleep(poll)
        if time.monotonic() - sent >= PING_SECONDS:
            sent = time.monotonic()
            yield "ping", None
