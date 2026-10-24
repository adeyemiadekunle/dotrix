"""A coding turn's files, for the session's Changes and Files: its diff, the repository's tree as
the turn leaves it, and any file before and after.

Read from the project's checkout (`modules/code`), at the commit the turn started from (fetched into
it on demand), with the turn's diff applied in a scratch index (`git apply --cached`), never a working
copy: the same for cloud and local turns, before their changes are pushed and after. `.dotrix/` is
never shown (it lives on the platform, not in the repo).
"""
from __future__ import annotations

import hashlib
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.errors import Conflict, NotFound, Unprocessable
from dotrix_backend.modules.code.checkouts import (
    CheckoutError,
    CodeCheckouts,
    RepoRef,
    auth_env,
    run_git,
)
from dotrix_backend.modules.code.service import CodeService
from dotrix_backend.modules.connectors.models import ConnectedRepo, GitHubInstallation
from dotrix_backend.modules.projects.deps import ProjectAccess

from .models import CodingRun
from .schemas import CodingDiff, CodingFile, CodingTree, CodingTreeEntry

MAX_ENTRIES = 20_000  # paths listed in a tree
MAX_FILE_BYTES = 1_000_000  # of a file shown (each side)
FETCH_TIMEOUT = 180
# A turn's tree as it leaves it: (project, base, the diff's digest) -> the tree's id, while the
# checkout that holds its objects lasts (a sync swaps the checkout; it's worked out again).
_trees: dict[tuple[uuid.UUID, str, str], str] = {}


class TurnFilesUnavailable(Conflict):
    code = "files_unavailable"


class TurnFiles:
    def __init__(self, session: AsyncSession, checkouts: CodeCheckouts | None) -> None:
        self.session, self.checkouts = session, checkouts

    async def diff(self, access: ProjectAccess, run: CodingRun) -> CodingDiff:
        """The turn's changes as a patch, with each file's counts (empty until it has any)."""
        return CodingDiff(base_sha=run.base_sha, diff=await self._diff(run) or "", files=list(run.files_changed or []))

    async def tree(self, access: ProjectAccess, run: CodingRun) -> CodingTree:
        """Every path in the repository as the turn leaves it (deleted ones too), with how it changed."""
        root, base, after = await self._prepared(run)
        listing = await run_git(root, "ls-tree", "-r", "-z", "--long", after)
        changed = await self._statuses(root, base, after)
        entries: list[CodingTreeEntry] = []
        for line in listing.split("\0"):
            if not line:
                continue
            meta, path = line.split("\t", 1)
            _, kind, _, size = meta.split(None, 3)
            if kind != "blob" or _hidden(path):
                continue
            entries.append(CodingTreeEntry(path=path, status=changed.get(path, "unchanged"),
                                           size=int(size) if size.strip().isdigit() else None))
        entries += [CodingTreeEntry(path=p, status="deleted", size=None) for p, s in changed.items() if s == "deleted"]
        entries.sort(key=lambda e: e.path)
        return CodingTree(base_sha=base, entries=entries[:MAX_ENTRIES], truncated=len(entries) > MAX_ENTRIES)

    async def file(self, access: ProjectAccess, run: CodingRun, path: str) -> CodingFile:
        """One file before the turn and after it (None where it didn't exist), unless binary or too large."""
        if not path or path.startswith("/") or ".." in path.split("/") or "\0" in path or _hidden(path):
            raise Unprocessable("Not a path in the repository")
        root, base, after = await self._prepared(run)
        before_text, before_size = await _blob(root, base, path)
        after_text, after_size = await _blob(root, after, path)
        if before_size is None and after_size is None:
            raise NotFound("No such file in this turn")
        status = "added" if before_size is None else "deleted" if after_size is None else (
            "modified" if before_text != after_text else "unchanged")
        too_large = max(before_size or 0, after_size or 0) > MAX_FILE_BYTES
        binary = not too_large and any("\0" in (t or "") for t in (before_text, after_text))
        hide = too_large or binary
        return CodingFile(path=path, status=status, before=None if hide else before_text,
                          after=None if hide else after_text, binary=binary, too_large=too_large)

    # -- the turn's tree -------------------------------------------------------------------

    async def _diff(self, run: CodingRun) -> str | None:
        row = (await self.session.execute(select(CodingRun.diff, CodingRun.pending_patch).where(
            CodingRun.workspace_id == run.workspace_id, CodingRun.id == run.id,
        ))).first()
        return (row[0] or row[1]) if row else None

    async def _prepared(self, run: CodingRun) -> tuple[Path, str, str]:
        """The checkout, the turn's base commit (in it), and the tree the turn leaves."""
        if self.checkouts is None:
            raise TurnFilesUnavailable("Reading code isn't set up on this server")
        if not run.base_sha:
            raise TurnFilesUnavailable("The turn hasn't started on a commit yet")
        checkout = await CodeService(self.session, self.checkouts).ensure(run.workspace_id, run.project_id)
        if checkout is None:
            raise TurnFilesUnavailable("The project's repository isn't checked out here (is it connected?)")
        diff = await self._diff(run) or ""
        key = (run.project_id, run.base_sha, hashlib.sha256(diff.encode()).hexdigest())
        async with self.checkouts.held(run.project_id):
            root = checkout.root
            try:
                await self._have(root, run)
                tree = _trees.get(key)
                if tree is None or not await _exists(root, tree):
                    tree = await _apply(root, run.base_sha, diff)
                    _trees[key] = tree
            except CheckoutError as exc:
                raise TurnFilesUnavailable(f"The turn's files can't be read: {exc}") from exc
        return root, run.base_sha, tree

    async def _have(self, root: Path, run: CodingRun) -> None:
        """The turn's base commit in the checkout: fetched from the repository when it isn't."""
        assert run.base_sha and self.checkouts is not None
        if await _exists(root, f"{run.base_sha}^{{commit}}"):
            return
        if self.checkouts.remote is None:
            raise TurnFilesUnavailable("Fetching from GitHub isn't set up on this server")
        found = (await self.session.execute(
            select(ConnectedRepo, GitHubInstallation)
            .join(GitHubInstallation, GitHubInstallation.id == ConnectedRepo.installation_ref)
            .where(ConnectedRepo.project_id == run.project_id, ConnectedRepo.workspace_id == run.workspace_id)
        )).first()
        if found is None:
            raise TurnFilesUnavailable("The project's repository was disconnected")
        repo, installation = found
        url, token = await self.checkouts.remote(RepoRef(
            workspace_id=repo.workspace_id, project_id=repo.project_id, installation_id=installation.installation_id,
            full_name=repo.full_name, default_branch=repo.default_branch,
        ))
        await run_git(root, "fetch", "-q", "--depth", "1", "--no-tags", "--no-write-fetch-head", url, run.base_sha,
                      env=auth_env(url, token), timeout=FETCH_TIMEOUT)

    async def _statuses(self, root: Path, base: str, after: str) -> dict[str, str]:
        out = await run_git(root, "diff-tree", "-r", "-z", "--no-renames", "--name-status", base, after)
        parts = [p for p in out.split("\0") if p]
        names = {"A": "added", "D": "deleted", "M": "modified", "T": "modified"}
        return {parts[i + 1]: names.get(parts[i][:1], "modified") for i in range(0, len(parts) - 1, 2)}


def _hidden(path: str) -> bool:
    return path == ".dotrix" or path.startswith(".dotrix/")


async def _exists(root: Path, rev: str) -> bool:
    try:
        await run_git(root, "cat-file", "-e", rev)
        return True
    except CheckoutError:
        return False


async def _apply(root: Path, base: str, diff: str) -> str:
    """The tree `base` becomes with `diff` applied, written as a tree object (no working copy)."""
    with tempfile.TemporaryDirectory(prefix="dotrix-turn-") as tmp:
        index = Path(tmp) / "index"
        env = {"GIT_INDEX_FILE": str(index)}
        await run_git(root, "read-tree", base, env=env)
        if diff.strip():
            patch = Path(tmp) / "turn.patch"
            patch.write_bytes(diff.encode())
            await run_git(root, "apply", "--cached", "--binary", "--whitespace=nowarn", str(patch), env=env)
        return (await run_git(root, "write-tree", env=env)).strip()


async def _blob(root: Path, tree: str, path: str) -> tuple[str | None, int | None]:
    """A file's text in a tree and its size (None, None: not there)."""
    try:
        size = int((await run_git(root, "cat-file", "-s", f"{tree}:{path}")).strip())
    except (CheckoutError, ValueError):
        return None, None
    if size > MAX_FILE_BYTES:
        return None, size
    return await run_git(root, "cat-file", "blob", f"{tree}:{path}"), size
