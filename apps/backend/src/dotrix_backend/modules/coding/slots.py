"""How many coding runs work at once in one worker (`DOTRIX_CODING_MAX_RUNS`), so a machine runs
no more sandboxes than its memory and CPUs hold. A run past the limit waits for a free sandbox,
saying so, and can still be stopped while it waits. Per process: each worker has its own."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

POLL_SECONDS = 3.0  # how often a waiting run checks whether it was stopped


class Stopped(Exception):
    """Stopped while waiting for a free sandbox."""


class RunSlots:
    def __init__(self, limit: int, *, poll_seconds: float = POLL_SECONDS) -> None:
        self.limit = limit  # 0: no limit
        self._free = asyncio.Semaphore(limit) if limit else None
        self._poll = poll_seconds

    @asynccontextmanager
    async def take(
        self, *, on_wait: Callable[[], Awaitable[None]], stopped: Callable[[], Awaitable[bool]],
    ) -> AsyncIterator[None]:
        if self._free is None:
            yield
            return
        if self._free.locked():
            await on_wait()
        while True:
            try:
                await asyncio.wait_for(self._free.acquire(), timeout=self._poll)
                break
            except TimeoutError:
                if await stopped():
                    raise Stopped from None
        try:
            yield
        finally:
            self._free.release()
