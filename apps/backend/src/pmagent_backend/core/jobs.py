"""Background jobs: work that shouldn't happen inside a request (sending email, password-reset
requests) or that outlives one (agent runs, see `modules/agents/queue.py`).

Where jobs execute follows PMAGENT_JOBS:
- "worker": queued in Redis (arq) for `python -m pmagent_backend.worker`; retried on failure
  and kept across API restarts.
- "local": an asyncio task in the API process, after the response (development).
- "inline": awaited in the caller (tests).

Jobs are functions `async def job(ctx: JobContext, **kwargs)` registered by name in
`pmagent_backend.jobs.JOBS`. Arguments must be JSON-friendly, since they may sit in a queue.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from .email import EmailMessage, EmailSender
from .settings import Settings
from .storage import BlobStorage

logger = logging.getLogger(__name__)

QUEUE_NAME = "pmagent:jobs"


@dataclass(frozen=True)
class JobContext:
    """What a job gets to work with, wherever it runs."""

    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]]
    settings: Settings
    email: EmailSender  # the real provider (a job must not enqueue its own email again)
    storage: BlobStorage | None = None  # document originals (None when storage isn't configured)
    embedder: Any = None  # the search index's embedding model (None: keyword search only)


JobFunction = Callable[..., Awaitable[Any]]


class Jobs(Protocol):
    async def enqueue(self, name: str, **kwargs: Any) -> None: ...


class InlineJobs:
    def __init__(self, ctx: JobContext, registry: Mapping[str, JobFunction]) -> None:
        self.ctx, self.registry = ctx, registry

    async def enqueue(self, name: str, **kwargs: Any) -> None:
        await self.registry[name](self.ctx, **kwargs)


class LocalJobs:
    """Runs each job as a task in this process. Failures are logged, not retried."""

    def __init__(self, ctx: JobContext, registry: Mapping[str, JobFunction]) -> None:
        self.ctx, self.registry = ctx, registry
        self._tasks: set[asyncio.Task[None]] = set()

    async def enqueue(self, name: str, **kwargs: Any) -> None:
        job = self.registry[name]  # an unknown name fails in the request, not later
        task = asyncio.create_task(self._run(name, job, kwargs))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def run(self, name: str, **kwargs: Any) -> None:
        """Run a job now and wait for it (a periodic job, so runs never overlap)."""
        await self._run(name, self.registry[name], kwargs)

    async def _run(self, name: str, job: JobFunction, kwargs: dict[str, Any]) -> None:
        try:
            await job(self.ctx, **kwargs)
        except Exception:
            logger.exception("job %s failed", name)

    async def drain(self, timeout: float = 10) -> None:
        """Let queued jobs finish (on shutdown)."""
        if self._tasks:
            await asyncio.wait(set(self._tasks), timeout=timeout)


class QueuedJobs:
    def __init__(self, redis: Any, queue_name: str = QUEUE_NAME) -> None:
        self.redis, self.queue_name = redis, queue_name

    async def enqueue(self, name: str, **kwargs: Any) -> None:
        await self.redis.enqueue_job(name, _queue_name=self.queue_name, **kwargs)


class QueuedEmailSender:
    """The API's EmailSender: each email is a `send_email` job, so sending never slows a
    request (or reveals, by its timing, that an address has an account)."""

    def __init__(self, jobs: Jobs) -> None:
        self.jobs = jobs

    async def send(self, message: EmailMessage) -> None:
        await self.jobs.enqueue(
            "send_email", to=message.to, subject=message.subject, body=message.body, html=message.html
        )


def get_jobs(request: Request) -> Jobs:
    return request.app.state.jobs
