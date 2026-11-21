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
            stream.write("worktree maintenance\n")
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


def _snapshot_ref(tree: Path, *, cleanup: bool = False) -> str:
    kind = "worktree-cleanups" if cleanup else "worktree-snapshots"
    return f"refs/dotrix/{kind}/{tree.parent.name}/{tree.name}"


async def _save_snapshot(repo: Path, ref: str, base: str, content: str) -> str:
    snapshot = (await git(
        repo, "-c", "user.name=Dotrix", "-c", "user.email=dotrix@localhost",
        "commit-tree", "--no-gpg-sign", content, "-p", base, "-m", "Dotrix local worktree snapshot",
    )).strip()
    await git(repo, "update-ref", ref, snapshot)
    return snapshot


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
        return await _save_snapshot(repo, _snapshot_ref(tree), base, content)


async def cleanup_worktree(repo: Path, tree: Path) -> None:
    """Save a recovery point and remove a clean managed checkout."""
    with _reserve(tree):
        if not tree.is_dir():
            raise RuntimeError("The managed worktree is missing.")
        await require_worktree_owner(repo, tree)
        base, content = (await git(tree, "rev-parse", "HEAD", "HEAD^{tree}")).split()
        if await git_bytes(tree, "status", "--porcelain=v1", "-z", "--ignored=matching", "--untracked-files=normal",
                           "--ignore-submodules=none"):
            raise RuntimeError("The worktree has changes, untracked files, or ignored files. Its files were kept.")
        await _save_snapshot(repo, _snapshot_ref(tree, cleanup=True), base, content)
        await git(repo, "worktree", "remove", str(tree))


async def restore_worktree(repo: Path, tree: Path, *, cleanup: bool = False) -> None:
    """Restore a missing worktree at the saved base, with its snapshot staged."""
    with _reserve(tree):
        if tree.exists() or tree.is_symlink():
            raise RuntimeError("The worktree path already exists. Its files were kept.")
        ref = _snapshot_ref(tree, cleanup=cleanup)
        if not cleanup and not (await git(repo, "rev-parse", "--verify", ref, check=False)).strip():
            ref = _snapshot_ref(tree, cleanup=True)
        record = (await git(repo, "rev-list", "--parents", "-n", "1", ref, check=False)).split()
        if len(record) != 2:
            raise RuntimeError("No valid snapshot was found in this repository for that session.")
        snapshot, base = record
        # A manually removed folder may have a stale Git worktree registration.
        await git(repo, "-c", f"core.hooksPath={os.devnull}", "worktree", "add", "-q", "--force", "--detach", str(tree), base)
        await git(tree, "read-tree", "-m", "-u", base, snapshot)
