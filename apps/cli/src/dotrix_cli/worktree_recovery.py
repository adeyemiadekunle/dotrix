"""Local recovery of managed worktrees through explicit Git snapshots."""

from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from .runner import git, git_bytes, require_worktree_owner


@contextmanager
def _reserve(tree: Path):
    tree.parent.mkdir(parents=True, exist_ok=True)
    marker = tree.with_suffix(".active")
    try:
        with marker.open("x") as stream:
            stream.write("worktree snapshot or restore\n")
    except FileExistsError as exc:
        raise RuntimeError("The worktree is active or its last operation was interrupted. Its files were kept.") from exc
    try:
        yield
    except (asyncio.CancelledError, KeyboardInterrupt):
        # Git may still be finishing an operation after its caller was interrupted.
        raise
    except BaseException:
        marker.unlink()
        raise
    else:
        marker.unlink()


def _snapshot_ref(tree: Path) -> str:
    return f"refs/dotrix/worktree-snapshots/{tree.parent.name}/{tree.name}"


async def snapshot_worktree(repo: Path, tree: Path) -> str:
    """Save the current tracked and non-ignored files without changing the worktree's index."""
    with _reserve(tree):
        if not tree.is_dir():
            raise RuntimeError("The managed worktree is missing.")
        await require_worktree_owner(repo, tree)
        base = (await git(tree, "rev-parse", "HEAD")).strip()
        with TemporaryDirectory(prefix="dotrix-worktree-index-") as directory:
            env = {**os.environ, "GIT_INDEX_FILE": str(Path(directory) / "index")}
            # Preserve staged additions, including files added despite an ignore rule.
            entries = await git_bytes(tree, "ls-files", "--stage", "-z")
            await git_bytes(tree, "update-index", "-z", "--index-info", env=env, stdin=entries)
            await git(tree, "add", "-A", env=env)
            content = (await git(tree, "write-tree", env=env)).strip()
        snapshot = (await git(
            repo, "-c", "user.name=Dotrix", "-c", "user.email=dotrix@localhost",
            "commit-tree", "--no-gpg-sign", content, "-p", base, "-m", "Dotrix local worktree snapshot",
        )).strip()
        await git(repo, "update-ref", _snapshot_ref(tree), snapshot)
        return snapshot


async def restore_worktree(repo: Path, tree: Path) -> None:
    """Restore a missing worktree at the saved base, with its snapshot staged."""
    with _reserve(tree):
        if tree.exists() or tree.is_symlink():
            raise RuntimeError("The worktree path already exists. Its files were kept.")
        record = (await git(repo, "rev-list", "--parents", "-n", "1", _snapshot_ref(tree), check=False)).split()
        if len(record) != 2:
            raise RuntimeError("No valid snapshot was found in this repository for that session.")
        snapshot, base = record
        # A manually removed folder may have a stale Git worktree registration.
        await git(repo, "-c", f"core.hooksPath={os.devnull}", "worktree", "add", "-q", "--force", "--detach", str(tree), base)
        await git(tree, "read-tree", "-m", "-u", base, snapshot)
