"""Facts about a local git checkout: its root, remote, README, and a summary for the
Architecture agent.

Nothing here reads source code. The summary is built from tracked file *paths*
(`git ls-files`, so ignored files like .env are never seen), known package
manifests, and the start of the README; for Docker files it keeps only image and
service names, because compose files often carry passwords.
"""
from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit, urlunsplit

import yaml

README_NAMES = ("README.md", "readme.md", "README.rst", "README.txt", "README")
MANIFESTS = {
    "package.json", "pyproject.toml", "requirements.txt", "go.mod", "Cargo.toml", "Gemfile",
    "composer.json", "pom.xml", "build.gradle", "build.gradle.kts", "mix.exs", "pubspec.yaml",
}
COMPOSE_FILES = {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}
MANIFEST_DEPTH = 3  # root, apps/web/, services/api/…
MAX_MANIFEST_CHARS = 3_000
MAX_README_CHARS = 4_000
MAX_SUMMARY_CHARS = 40_000
MAX_TREE_LINES = 150


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8")
    except FileNotFoundError:  # git isn't installed
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def git_root(path: str | Path) -> Path | None:
    top = _git(Path(path), "rev-parse", "--show-toplevel")
    return Path(top) if top else None


def strip_credentials(url: str) -> str:
    """https://user:token@host/x -> https://host/x. Never send credentials anywhere."""
    if "://" not in url:
        return url  # git@host:owner/repo carries no password
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def remote_url(root: Path, name: str = "origin") -> str | None:
    url = _git(root, "remote", "get-url", name)
    return strip_credentials(url) if url else None


def read_readme(root: Path) -> str | None:
    for name in README_NAMES:
        path = root / name
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="ignore")
    return None


def suggest_key(name: str) -> str:
    """"kunemi" -> "KUN"; "kunemi-web" -> "KW"; always 2-10 letters/digits, starting with a letter."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+", name) if w]
    if len(words) > 1:
        key = "".join(w[0] for w in words)
    else:
        key = (words[0] if words else "PRJ")[:3]
    key = re.sub(r"[^A-Z0-9]", "", key.upper())
    if not key or not key[0].isalpha():
        key = "P" + key
    return (key + "X")[:10] if len(key) < 2 else key[:10]


# -- the summary the Architecture agent may read -------------------------------------


def _tree(files: list[str]) -> list[str]:
    dirs: Counter[str] = Counter()
    for f in files:
        parts = PurePosixPath(f).parts[:-1]
        for depth in range(1, min(len(parts), 3) + 1):
            dirs["/".join(parts[:depth])] += 1
    root_files = sorted(f for f in files if "/" not in f)
    lines = [f"{d}/  ({n} files)" for d, n in sorted(dirs.items())]
    if len(lines) > MAX_TREE_LINES:
        lines = lines[:MAX_TREE_LINES] + [f"… {len(dirs) - MAX_TREE_LINES} more folders"]
    return lines + [f"{f}" for f in root_files[:40]]


def _compose_summary(text: str) -> str:
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return "(unreadable compose file)"
    services = data.get("services") or {}
    return "\n".join(
        f"- {name}: {(spec or {}).get('image') or '(built from source)'}" for name, spec in services.items()
    ) or "(no services)"


def _dockerfile_summary(text: str) -> str:
    return "\n".join(line.strip() for line in text.splitlines() if line.strip().upper().startswith("FROM ")) or "(no FROM)"


def _package_json_summary(text: str) -> str:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text[:MAX_MANIFEST_CHARS]
    keep = {k: data[k] for k in ("name", "workspaces", "dependencies", "devDependencies", "engines") if k in data}
    if "scripts" in data:
        keep["scripts"] = sorted(data["scripts"])
    return json.dumps(keep, indent=2)[:MAX_MANIFEST_CHARS]


def repo_summary(root: Path) -> str:
    files = (_git(root, "ls-files") or "").splitlines()
    sections = [f"Repository: {root.name} ({len(files)} tracked files)", "", "## Layout", *_tree(files)]

    for rel in sorted(files):
        path = PurePosixPath(rel)
        if len(path.parts) > MANIFEST_DEPTH:
            continue
        full = root / rel
        if not full.is_file():
            continue
        name = path.name
        if name in MANIFESTS:
            text = full.read_text(encoding="utf-8", errors="ignore")
            body = _package_json_summary(text) if name == "package.json" else text[:MAX_MANIFEST_CHARS]
            sections += ["", f"## {rel}", body]
        elif name in COMPOSE_FILES:
            sections += ["", f"## {rel} (services and images only)", _compose_summary(full.read_text(encoding="utf-8", errors="ignore"))]
        elif name == "Dockerfile" or name.startswith("Dockerfile."):
            sections += ["", f"## {rel} (base images only)", _dockerfile_summary(full.read_text(encoding="utf-8", errors="ignore"))]

    readme = read_readme(root)
    if readme:
        sections += ["", "## README (start)", readme[:MAX_README_CHARS]]
    summary = "\n".join(sections)
    return summary if len(summary) <= MAX_SUMMARY_CHARS else summary[:MAX_SUMMARY_CHARS] + "\n… (truncated)"
