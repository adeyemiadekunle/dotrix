"""Global project registry: ~/.pmagent/registry.yaml maps project name -> root_dir.

Lets every command take `--project my-app` instead of a path, and is what a
future desktop app lists in a project switcher instead of re-scanning disk
for `.pmagent/` folders.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

REGISTRY_PATH = Path(os.path.expanduser("~/.pmagent/registry.yaml"))


def _load() -> dict:
    if not REGISTRY_PATH.exists():
        return {}
    return yaml.safe_load(REGISTRY_PATH.read_text()) or {}


def _save(data: dict) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(yaml.safe_dump(data))


def register(name: str, root_dir: str) -> None:
    data = _load()
    data[name] = os.path.abspath(root_dir)
    _save(data)


def list_projects() -> dict:
    return _load()


def resolve(name_or_path: str) -> str:
    """A registered name resolves to its root_dir; anything else (including
    ".", the default) is treated as a literal path, unchanged."""
    return _load().get(name_or_path, name_or_path)
