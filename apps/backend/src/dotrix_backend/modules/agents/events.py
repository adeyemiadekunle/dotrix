"""A run's events, kept: the steps it took, its reply as written, and each step's outcome.

The live stream (streams.py) is best effort: in-process, or through Redis with keys that
expire, and gone with the worker that wrote it. These rows are what's durable. The runner
records them as it streams (`RecordingStream`: text coalesced to about a second's worth, each
activity, a `step` marker whenever an attempt at a step begins, its `status` when it ends), so:
- a client that reconnects gets the current step's text even when the live stream is gone
  (the API restarted, Redis lost it, the worker died and the run is being resumed);
- `GET .../runs/{id}/events?after=<seq>` reads them a page at a time, from where a client was;
- the steps stay readable after the run (what the agents did, in order).
Recording never fails a run: a write that doesn't work is logged and skipped.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils.compat import uuid7

from .models import AgentRun, AgentRunEvent, RunEventKind, RunStatus
from .storage_backend import SessionFactory
from .streams import Stream

logger = logging.getLogger(__name__)

FLUSH_SECONDS = 1.0
FLUSH_CHARS = 2_000
KEEP_EVENTS = 2_000  # a run's latest; older ones are pruned when a step ends
PAGE_MAX = 500
POLL_SECONDS = 1.0
HEARTBEAT_SECONDS = 15.0
ACTIVE = (RunStatus.QUEUED, RunStatus.RUNNING)


async def add_event(
    session: AsyncSession, run: AgentRun, kind: RunEventKind, data: dict[str, Any], *, attempt: int | None = None,
) -> None:
    """Add an event in the caller's transaction (its seq the run's next)."""
    seq = select(func.coalesce(func.max(AgentRunEvent.seq), 0) + 1).where(
        AgentRunEvent.run_id == run.id).scalar_subquery()
    await session.execute(insert(AgentRunEvent).values(
        id=uuid7(), workspace_id=run.workspace_id, run_id=run.id, seq=seq,
        attempt=run.lease_token if attempt is None else attempt, kind=kind, data=data,
        created_at=datetime.now(UTC),
    ))


class RunRecorder:
    """Writes one run's events in their own transactions (never the run's)."""

    def __init__(self, session_factory: SessionFactory, workspace_id: uuid.UUID, run_id: uuid.UUID, attempt: int) -> None:
        self.session_factory, self.workspace_id, self.run_id, self.attempt = session_factory, workspace_id, run_id, attempt

    async def write(self, kind: RunEventKind, data: dict[str, Any]) -> None:
        for _ in range(3):  # a concurrent writer (a fenced-off attempt) may take the same seq
            try:
                async with self.session_factory() as session:
                    run = await session.scalar(select(AgentRun).where(
                        AgentRun.workspace_id == self.workspace_id, AgentRun.id == self.run_id))
                    if run is None:
                        return
                    await add_event(session, run, kind, data, attempt=self.attempt)
                    await session.commit()
                    return
            except IntegrityError:
                continue
            except Exception:
                logger.warning("agent run %s: couldn't record a %s event", self.run_id, kind, exc_info=True)
                return

    async def prune(self) -> None:
        try:
            async with self.session_factory() as session:
                last = await session.scalar(select(func.max(AgentRunEvent.seq)).where(
                    AgentRunEvent.workspace_id == self.workspace_id, AgentRunEvent.run_id == self.run_id))
                if last and last > KEEP_EVENTS:
                    await session.execute(delete(AgentRunEvent).where(
                        AgentRunEvent.workspace_id == self.workspace_id, AgentRunEvent.run_id == self.run_id,
                        AgentRunEvent.seq <= last - KEEP_EVENTS))
                    await session.commit()
        except Exception:
            logger.warning("agent run %s: couldn't prune its events", self.run_id, exc_info=True)


class RecordingStream:
    """The live stream, with every piece also kept (text coalesced)."""

    def __init__(self, inner: Stream, recorder: RunRecorder) -> None:
        self.inner, self.recorder = inner, recorder
        self._text: list[str] = []
        self._since = time.monotonic()
        self._flusher: asyncio.Task[None] | None = None

    async def begin(self, data: dict[str, Any]) -> None:
        await self.recorder.write(RunEventKind.STEP, data)
        self._flusher = asyncio.create_task(self._flush_idle())

    async def publish(self, delta: str) -> None:
        await self.inner.publish(delta)
        if not delta:
            return
        self._text.append(delta)
        if sum(map(len, self._text)) >= FLUSH_CHARS or time.monotonic() - self._since >= FLUSH_SECONDS:
            await self.flush()

    async def activity(self, label: str) -> None:
        await self.inner.activity(label)
        if label:
            await self.flush()
            await self.recorder.write(RunEventKind.ACTIVITY, {"label": label})

    async def flush(self) -> None:
        self._since = time.monotonic()
        if not self._text:
            return
        text, self._text = "".join(self._text), []
        await self.recorder.write(RunEventKind.TEXT, {"text": text})

    async def close(self) -> None:
        if self._flusher is not None:
            self._flusher.cancel()
        await self.flush()
        await self.recorder.prune()

    async def _flush_idle(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_SECONDS)
            if self._text and time.monotonic() - self._since >= FLUSH_SECONDS:
                await self.flush()


async def events_after(
    session: AsyncSession, run: AgentRun, after: int, limit: int,
) -> list[AgentRunEvent]:
    return list(await session.scalars(select(AgentRunEvent).where(
        AgentRunEvent.workspace_id == run.workspace_id, AgentRunEvent.run_id == run.id, AgentRunEvent.seq > after,
    ).order_by(AgentRunEvent.seq).limit(min(limit, PAGE_MAX))))


async def current_step(session: AsyncSession, run: AgentRun) -> tuple[int, str, str | None]:
    """(last seq, the current step's text so far, its latest activity), from the kept events."""
    start = await session.scalar(select(func.max(AgentRunEvent.seq)).where(
        AgentRunEvent.workspace_id == run.workspace_id, AgentRunEvent.run_id == run.id,
        AgentRunEvent.kind == RunEventKind.STEP)) or 0
    rows = list(await session.scalars(select(AgentRunEvent).where(
        AgentRunEvent.workspace_id == run.workspace_id, AgentRunEvent.run_id == run.id, AgentRunEvent.seq >= start,
    ).order_by(AgentRunEvent.seq)))
    text = "".join(r.data.get("text", "") for r in rows if r.kind is RunEventKind.TEXT)
    activity = next((r.data.get("label") for r in reversed(rows) if r.kind is RunEventKind.ACTIVITY), None)
    return (rows[-1].seq if rows else start), text, activity


async def follow_kept(
    session_factory: SessionFactory, workspace_id: uuid.UUID, run_id: uuid.UUID, *, poll_seconds: float = POLL_SECONDS,
) -> AsyncIterator[tuple[str, str]]:
    """The stream's events from the kept rows, for when the live stream is gone but the run is
    still active (being resumed, or its worker's stream lost): ("text", the step so far), then
    ("delta" | "activity", …) as rows arrive, ("text", …) again when a new step starts over, and
    ("end", "") once the run isn't active. Ping-free: the caller's heartbeat covers quiet spells."""
    async with session_factory() as session:
        run = await session.scalar(select(AgentRun).where(AgentRun.workspace_id == workspace_id, AgentRun.id == run_id))
        if run is None:
            yield ("end", "")
            return
        seq, text, activity = await current_step(session, run)
    yield ("text", text)
    if activity:
        yield ("activity", activity)
    quiet = 0.0
    while True:
        await asyncio.sleep(poll_seconds)
        async with session_factory() as session:
            run = await session.scalar(select(AgentRun).where(AgentRun.workspace_id == workspace_id, AgentRun.id == run_id))
            if run is None:
                break
            rows = await events_after(session, run, seq, PAGE_MAX)
            active = run.status in ACTIVE
        for row in rows:
            seq = row.seq
            if row.kind is RunEventKind.STEP:
                yield ("text", "")
            elif row.kind is RunEventKind.TEXT:
                yield ("delta", row.data.get("text", ""))
            elif row.kind is RunEventKind.ACTIVITY:
                yield ("activity", row.data.get("label", ""))
        if not active and not rows:
            break
        quiet = 0.0 if rows else quiet + poll_seconds
        if quiet >= HEARTBEAT_SECONDS:
            quiet = 0.0
            yield ("ping", "")
    yield ("end", "")


async def follow_run(
    streams: Any, session_factory: SessionFactory, workspace_id: uuid.UUID, run_id: uuid.UUID,
) -> AsyncIterator[tuple[str, str]]:
    """The live stream while there is one; once it's gone and the run is still active, the kept
    events (`follow_kept`), so a client never stops at a stream that died with its worker."""
    async for event, data in streams.follow(run_id):
        if event == "end":
            break
        yield (event, data)
    async with session_factory() as session:
        status = await session.scalar(select(AgentRun.status).where(
            AgentRun.workspace_id == workspace_id, AgentRun.id == run_id))
    if status in ACTIVE:
        async for event, data in follow_kept(session_factory, workspace_id, run_id):
            yield (event, data)
        return
    yield ("end", "")
