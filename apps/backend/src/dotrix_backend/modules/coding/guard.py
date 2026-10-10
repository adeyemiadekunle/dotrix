"""What a coding run's changes may not touch, checked before anything is committed or pushed.

The sandbox can't see these rules (it only edits files), so the worker checks the agent's
changes: `.dotrix/` lives on the platform and never goes into a code repo, CI workflows could
leak the repo's secrets when the PR's checks run, and `.git` is git's own.
"""
from __future__ import annotations

from pathlib import PurePosixPath

MAX_FILES = 500
MAX_PATCH_BYTES = 8_000_000


def refused(path: str) -> str | None:
    """Why a changed path isn't allowed in a coding run's PR, or None."""
    parts = PurePosixPath(path).parts
    if ".dotrix" in parts:
        return f"{path}: .dotrix/ stays on the platform, never in a code repo"
    if ".git" in parts:
        return f"{path}: git's own folder"
    if path.startswith(".github/workflows/"):
        return f"{path}: CI workflows aren't changed by coding runs (they'd run with the repo's secrets)"
    return None


def check(paths: list[str]) -> list[str]:
    """Every reason the changes can't be pushed (empty: they can)."""
    reasons = [reason for path in paths if (reason := refused(path))]
    if len(paths) > MAX_FILES:
        reasons.append(f"{len(paths)} files changed, more than {MAX_FILES}")
    return reasons
