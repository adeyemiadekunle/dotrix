"""Canonical repo URLs, so one repo always matches however it was cloned.

    https://user:token@GitHub.com/Acme/kunemi.git  ->  https://github.com/Acme/kunemi
    git@github.com:Acme/kunemi.git                 ->  https://github.com/Acme/kunemi
    ssh://git@github.com/Acme/kunemi               ->  https://github.com/Acme/kunemi

Credentials embedded in a remote (common with HTTPS clones) are always dropped:
they must never be stored or sent anywhere.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

_SCP_LIKE = re.compile(r"^(?:[\w.-]+@)?(?P<host>[\w.-]+):(?P<path>(?!//)[^\s]+)$")


def normalize_repo_url(url: str) -> str:
    raw = url.strip()
    if not raw:
        raise ValueError("Repo URL is empty")
    if "://" not in raw:
        match = _SCP_LIKE.match(raw)  # git@host:owner/repo.git
        if not match:
            raise ValueError(f"Not a repo URL: {raw!r}")
        host, path = match["host"], match["path"]
    else:
        parts = urlsplit(raw)
        if parts.scheme.lower() not in ("https", "http", "ssh", "git", "git+ssh"):
            raise ValueError(f"Unsupported repo URL scheme {parts.scheme!r}")
        if not parts.hostname:
            raise ValueError(f"Not a repo URL: {raw!r}")
        host = parts.hostname  # userinfo and port dropped
        path = parts.path
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    if not path or ".." in path.split("/"):
        raise ValueError(f"Not a repo URL: {raw!r}")
    return f"https://{host.lower()}/{path}"
