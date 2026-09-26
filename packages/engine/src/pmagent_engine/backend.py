"""Locking wrapper around FilesystemBackend.

Once more than one process can touch the same `.pmagent/` folder at once (an
interactive `chat` session, background `run` jobs, and now coding agents
updating tasks through the CLI), plain FilesystemBackend has no protection
against two writers hitting the same file. This wraps every mutating call in
a per-file OS lock so concurrent writers serialize. Reads are never locked.

Lock paths are `<root>/.locks/<path>.lock`, where `path` is what this backend
receives. CompositeBackend strips the `/pmagent/` route prefix first, so
`/pmagent/tasks/TASK-x.md` locks `.locks/tasks/TASK-x.md.lock`. tasks.py takes
the exact same lock, which is how the CLI and the agent serialize on a task.

Verified against deepagents 0.7.19, whose FilesystemBackend exposes
write/edit/delete and async awrite/aedit/adelete. Both sets are wrapped:
the CLI uses sync invoke(), but a future async server would go through the
a* methods and would otherwise skip the lock silently.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from deepagents.backends import FilesystemBackend
from filelock import FileLock


class LockingFilesystemBackend(FilesystemBackend):
    def _lock_for(self, path: str) -> FileLock:
        # FilesystemBackend stores its root_dir as self.cwd (there is no
        # self.root_dir attribute; the previous version raised on first write).
        lock_path = Path(self.cwd) / ".locks" / (path.lstrip("/") + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        return FileLock(str(lock_path), timeout=30)

    # -- sync ---------------------------------------------------------------
    def write(self, file_path: str, *args, **kwargs):
        with self._lock_for(file_path):
            return super().write(file_path, *args, **kwargs)

    def edit(self, file_path: str, *args, **kwargs):
        with self._lock_for(file_path):
            return super().edit(file_path, *args, **kwargs)

    def delete(self, file_path: str, *args, **kwargs):
        with self._lock_for(file_path):
            return super().delete(file_path, *args, **kwargs)

    # -- async (don't block the event loop while waiting on the lock) --------
    async def _locked(self, file_path: str, coro_fn, *args, **kwargs):
        lock = self._lock_for(file_path)
        await asyncio.to_thread(lock.acquire)
        try:
            return await coro_fn(file_path, *args, **kwargs)
        finally:
            lock.release()

    async def awrite(self, file_path: str, *args, **kwargs):
        return await self._locked(file_path, super().awrite, *args, **kwargs)

    async def aedit(self, file_path: str, *args, **kwargs):
        return await self._locked(file_path, super().aedit, *args, **kwargs)

    async def adelete(self, file_path: str, *args, **kwargs):
        return await self._locked(file_path, super().adelete, *args, **kwargs)
