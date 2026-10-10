"""Checkouts of connected repos, for agents to read (agents v2 step 5b).

Each project's repo is a shallow copy of its default branch at `{code_dir}/{workspace}/{project}`,
on the machine that runs agents (the worker, or the API in local mode). A sync fetches it afresh
into a new folder and swaps it in, so a reader never sees half a checkout. The installation token
reaches git through its environment (never the URL, the command line, or `.git/config`), so it
isn't stored or shown in the process list. Nothing in a checkout is ever run.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import shutil
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from dotrix_backend.core.settings import Settings

logger = logging.getLogger(__name__)

FETCH_TIMEOUT = 300


@dataclass(frozen=True)
class RepoRef:
    """What a sync needs to know about a connected repo."""

    workspace_id: uuid.UUID
    project_id: uuid.UUID
    installation_id: int  # GitHub's
    full_name: str
    default_branch: str


# Where to fetch a repo from, and the token to send (None: no auth, e.g. a local path in tests).
Remote = Callable[[RepoRef], Awaitable[tuple[str, str | None]]]


class CheckoutError(Exception):
    """A sync that didn't work; the message is safe to show and store (no tokens)."""


class CodeCheckouts:
    def __init__(self, base_dir: Path, remote: Remote | None, *, max_bytes: int) -> None:
        self.base_dir = base_dir
        self.remote = remote
        self.max_bytes = max_bytes
        self._locks: dict[uuid.UUID, asyncio.Lock] = {}

    def path(self, workspace_id: uuid.UUID, project_id: uuid.UUID) -> Path:
        return self.base_dir / str(workspace_id) / str(project_id)

    async def head(self, workspace_id: uuid.UUID, project_id: uuid.UUID) -> str | None:
        """The commit checked out here, or None if there's no checkout."""
        root = self.path(workspace_id, project_id)
        if not (root / ".git").exists():
            return None
        try:
            return (await run_git(root, "rev-parse", "HEAD")).strip() or None
        except CheckoutError:
            return None

    async def sync(self, ref: RepoRef) -> str:
        """Fetch the default branch's latest commit and swap it in; returns its sha."""
        if self.remote is None:
            raise CheckoutError("Reading code isn't set up here (the GitHub App isn't configured)")
        lock = self._locks.setdefault(ref.project_id, asyncio.Lock())
        async with lock:
            url, token = await self.remote(ref)
            target = self.path(ref.workspace_id, ref.project_id)
            target.parent.mkdir(parents=True, exist_ok=True)
            fresh = target.parent / f".{ref.project_id}.{uuid.uuid4().hex[:8]}"
            env = auth_env(url, token)
            try:
                await run_git(fresh.parent, "init", "-q", str(fresh))
                await run_git(
                    fresh, "fetch", "-q", "--depth", "1", "--no-tags", url,
                    f"refs/heads/{ref.default_branch}", env=env, timeout=FETCH_TIMEOUT,
                )
                await run_git(fresh, "checkout", "-q", "--detach", "FETCH_HEAD")
                size = await asyncio.to_thread(_size, fresh)
                if size > self.max_bytes:
                    raise CheckoutError(
                        f"{ref.full_name} is {size // 1_000_000:,} MB, more than the "
                        f"{self.max_bytes // 1_000_000:,} MB limit (DOTRIX_CODE_MAX_MB)"
                    )
                sha = (await run_git(fresh, "rev-parse", "HEAD")).strip()
                await asyncio.to_thread(_swap, fresh, target)
            except BaseException:
                await asyncio.to_thread(shutil.rmtree, fresh, True)
                raise
        logger.info("checked out %s at %s for project %s", ref.full_name, sha[:7], ref.project_id)
        return sha

    async def remove(self, workspace_id: uuid.UUID, project_id: uuid.UUID) -> None:
        await asyncio.to_thread(shutil.rmtree, self.path(workspace_id, project_id), True)

    async def prune(self, keep: set[tuple[uuid.UUID, uuid.UUID]]) -> int:
        """Delete checkouts of projects no longer connected (or moved); returns how many."""
        return await asyncio.to_thread(self._prune, {(str(w), str(p)) for w, p in keep})

    def _prune(self, keep: set[tuple[str, str]]) -> int:
        removed = 0
        if not self.base_dir.exists():
            return 0
        for workspace in self.base_dir.iterdir():
            if not workspace.is_dir():
                continue
            for project in workspace.iterdir():
                if project.name.startswith("."):  # a sync in progress, or one cut off
                    continue
                if (workspace.name, project.name) not in keep:
                    shutil.rmtree(project, True)
                    removed += 1
        return removed


def auth_env(url: str, token: str | None) -> dict[str, str]:
    """The token as an HTTP header for this one URL, through git's environment config."""
    if token is None:
        return {}
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"http.{url}.extraheader",
        "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
    }


async def run_git(cwd: Path, *args: str, env: dict[str, str] | None = None, timeout: float = 60) -> str:
    process = await asyncio.create_subprocess_exec(
        "git", "-c", "credential.helper=", "-c", "core.hooksPath=/dev/null", *args,
        cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        # No prompts, and no LFS downloads even where git-lfs is set up globally: agents read
        # source, not large binaries.
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1", **(env or {})},
    )
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError as exc:
        process.kill()
        raise CheckoutError("Fetching the repository took too long") from exc
    if process.returncode != 0:
        lines = err.decode(errors="replace").strip().splitlines()
        # git's own last line ("fatal: couldn't find remote ref main"); it never holds the token.
        raise CheckoutError(lines[-1][:300] if lines else f"git {args[0]} failed")
    return out.decode(errors="replace")


def _size(root: Path) -> int:
    total = 0
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != ".git"]
        total += sum((Path(folder) / f).lstat().st_size for f in files)
    return total


def _swap(fresh: Path, target: Path) -> None:
    old = target.parent / f".{target.name}.old.{uuid.uuid4().hex[:8]}"
    if target.exists():
        target.rename(old)
    fresh.rename(target)
    shutil.rmtree(old, True)


def github_remote(app: object) -> Remote:
    """Fetch from github.com with a fresh installation token (an hour long, never stored)."""

    async def remote(ref: RepoRef) -> tuple[str, str | None]:
        token = await app.access_token(ref.installation_id)  # type: ignore[attr-defined]
        return f"https://github.com/{ref.full_name}.git", token

    return remote


def build_checkouts(settings: Settings) -> CodeCheckouts:
    from dotrix_backend.modules.connectors.github_app import GitHubAppClient

    app = GitHubAppClient(settings)
    return CodeCheckouts(
        Path(settings.code_dir).expanduser(),
        github_remote(app) if app.configured else None,
        max_bytes=settings.code_max_mb * 1_000_000,
    )
