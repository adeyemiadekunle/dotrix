"""Small, expiring Redis aggregates for the operator console."""
from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from redis.exceptions import RedisError

from .email import EmailMessage, EmailSender, EmailSendError

HEARTBEAT = "dotrix:operations:worker"
EMAIL_ACCEPTED = "dotrix:operations:email-accepted"


class OperationsSnapshot(BaseModel):
    worker_revision: str | None = None
    worker_heartbeat_at: datetime | None = None
    email_last_accepted_at: datetime | None = None
    email_retries_today: int = 0
    email_permanent_failures_today: int = 0
    first_nova_event_samples_today: int = 0
    first_nova_event_mean_ms_today: float | None = None


class Operations:
    def __init__(self, redis: Any) -> None:
        self.redis = redis

    @staticmethod
    def day_key() -> str:
        return f"dotrix:operations:{datetime.now(UTC).date().isoformat()}"

    async def heartbeat(self, revision: str | None) -> None:
        with suppress(RedisError, TimeoutError):
            async with asyncio.timeout(0.5), self.redis.pipeline() as pipe:
                pipe.hset(HEARTBEAT, mapping={"revision": revision or "", "at": datetime.now(UTC).isoformat()})
                pipe.expire(HEARTBEAT, 90)
                await pipe.execute()

    async def count(self, field: str, *, duration_ms: int | None = None) -> None:
        with suppress(RedisError, TimeoutError):
            key = self.day_key()
            async with asyncio.timeout(0.5), self.redis.pipeline() as pipe:
                pipe.hincrby(key, field, 1)
                if duration_ms is not None:
                    pipe.hincrby(key, f"{field}_total_ms", duration_ms)
                pipe.expire(key, 172800)
                await pipe.execute()

    async def email_accepted(self) -> None:
        with suppress(RedisError, TimeoutError):
            async with asyncio.timeout(0.5):
                await self.redis.set(EMAIL_ACCEPTED, datetime.now(UTC).isoformat(), ex=604800)

    async def snapshot(self) -> OperationsSnapshot | None:
        with suppress(RedisError, TimeoutError, ValueError):
            async with asyncio.timeout(0.5), self.redis.pipeline(transaction=False) as pipe:
                pipe.hgetall(HEARTBEAT)
                pipe.get(EMAIL_ACCEPTED)
                pipe.hgetall(self.day_key())
                worker, last_email, today = await pipe.execute()
            samples = int(today.get(b"first_nova_event", 0))
            return OperationsSnapshot(
                worker_revision=worker.get(b"revision") or None,
                worker_heartbeat_at=worker.get(b"at"),
                email_last_accepted_at=last_email,
                email_retries_today=int(today.get(b"email_retry", 0)),
                email_permanent_failures_today=int(today.get(b"email_permanent_failure", 0)),
                first_nova_event_samples_today=samples,
                first_nova_event_mean_ms_today=(
                    round(int(today.get(b"first_nova_event_total_ms", 0)) / samples, 1) if samples else None
                ),
            )
        return None

    async def first_nova_event(self, opened_at: float) -> None:
        await self.count("first_nova_event", duration_ms=round((time.monotonic() - opened_at) * 1000))


class ObservedEmailSender:
    def __init__(self, sender: EmailSender, operations: Operations) -> None:
        self.sender, self.operations = sender, operations

    async def send(self, message: EmailMessage) -> None:
        try:
            await self.sender.send(message)
        except EmailSendError as exc:
            if not exc.retryable:
                await self.operations.count("email_permanent_failure")
            raise
        await self.operations.email_accepted()
