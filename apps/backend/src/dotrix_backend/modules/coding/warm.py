"""Warm coding sandboxes (Phase B): a session's sandbox kept between its turns, in the process that
runs them, so a follow-up starts where the last turn ended (its files, its installed dependencies,
Claude Code's transcript) instead of from a fresh copy.

The pool is only a cache. A turn that finds no warm sandbox (another process, a restart, the idle
timeout) starts a fresh one and restores the session's saved transcript, so nothing depends on it.
It keeps at most `per_workspace` sandboxes for each workspace (the least recently used is closed),
and closes any left unused for `idle_seconds`.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

from .sandbox import SandboxSession

logger = logging.getLogger(__name__)


@dataclass
class _Warm:
    box: SandboxSession
    workspace_id: uuid.UUID
    used: float  # time.monotonic() when its last turn ended


async def close_quietly(box: SandboxSession) -> None:
    try:
        await box.close()
    except Exception:
        logger.warning("couldn't close a coding sandbox", exc_info=True)


class WarmPool:
    def __init__(self, idle_seconds: float, per_workspace: int) -> None:
        self.idle_seconds, self.per_workspace = idle_seconds, per_workspace
        self._boxes: dict[uuid.UUID, _Warm] = {}

    def take(self, session_id: uuid.UUID) -> SandboxSession | None:
        """The session's warm sandbox, out of the pool for the turn (or None)."""
        found = self._boxes.pop(session_id, None)
        return found.box if found else None

    async def put(self, session_id: uuid.UUID, workspace_id: uuid.UUID, box: SandboxSession) -> list[uuid.UUID]:
        """Keep a session's sandbox after its turn; the sessions whose sandboxes were closed to stay
        within the workspace's limit (this one, when the limit is 0)."""
        if self.per_workspace <= 0:
            await close_quietly(box)
            return [session_id]
        self._boxes[session_id] = _Warm(box, workspace_id, time.monotonic())
        mine = sorted((w.used, sid) for sid, w in self._boxes.items() if w.workspace_id == workspace_id)
        closed: list[uuid.UUID] = []
        while len(mine) > self.per_workspace:
            _, oldest = mine.pop(0)
            await self.close(oldest)
            closed.append(oldest)
        return closed

    async def close(self, session_id: uuid.UUID) -> bool:
        found = self._boxes.pop(session_id, None)
        if found is not None:
            await close_quietly(found.box)
        return found is not None

    def idle(self) -> list[uuid.UUID]:
        now = time.monotonic()
        return [sid for sid, w in self._boxes.items() if now - w.used > self.idle_seconds]

    def sessions(self) -> list[uuid.UUID]:
        return list(self._boxes)

    async def close_all(self) -> None:
        for sid in list(self._boxes):
            await self.close(sid)
