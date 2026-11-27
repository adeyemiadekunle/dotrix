"""The programs native local Code needs that a release ships beside the standalone CLI (apps/cli/scripts/
bundle_tools.py): the Kai runtime's fx, and on Linux a static Bubblewrap. A release's own copy wins over one on
PATH, so a person needs nothing installed beyond the OS, and an fx or bwrap someone else put on PATH earlier is
not used in its place. From source (not frozen), nothing is bundled and PATH is used, as before.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def bundle_dir() -> Path | None:
    """`bin/` beside the standalone CLI's executable, when this is a release build that has one."""
    if not getattr(sys, "frozen", False):
        return None
    folder = Path(sys.executable).resolve().parent / "bin"
    return folder if folder.is_dir() else None


def _bundled(name: str) -> str | None:
    folder = bundle_dir()
    if folder is None:
        return None
    candidate = folder / name
    return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None


def fx() -> str | None:
    """The fx native Code runs: the bundled Kai runtime's, else the first on PATH."""
    return _bundled("fx") or shutil.which("fx")


def bwrap() -> str | None:
    """Linux: the bundled static Bubblewrap, else the system's."""
    return _bundled("bwrap") or shutil.which("bwrap")
