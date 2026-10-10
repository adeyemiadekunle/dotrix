"""Linking a local repo to a platform project, and mirroring its `.dotrix/`.

The platform is the source of truth; the local `.dotrix/` is a read mirror for the
CLI, Claude Code, and Codex, kept out of git. Link state lives in
`.dotrix/.platform.json` (local only, never synced).

`pull` asks for what changed since the last revision, writes it, applies
deletions, and never overwrites a file edited locally since the last pull unless
forced. If anything conflicted, the revision isn't advanced, so the next pull
reports it again instead of silently skipping it.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

from .platform import PlatformClient, PlatformError

STATE_FILE = ".platform.json"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class LinkState:
    api_url: str
    workspace_id: str
    project_id: str
    project_key: str
    project_name: str
    revision: int = 0
    files: dict[str, str] = field(default_factory=dict)  # path -> sha256 as last pulled

    @property
    def issues_path(self) -> str:
        return f"/workspaces/{self.workspace_id}/projects/{self.project_id}/issues"

    @property
    def knowledge_path(self) -> str:
        return f"/workspaces/{self.workspace_id}/projects/{self.project_id}/knowledge"

    @classmethod
    def load(cls, dotrix_dir: str | Path) -> LinkState | None:
        path = Path(dotrix_dir) / STATE_FILE
        if not path.exists():
            return None
        return cls(**json.loads(path.read_text(encoding="utf-8")))

    def save(self, dotrix_dir: str | Path) -> None:
        path = Path(dotrix_dir) / STATE_FILE
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.replace(tmp, path)


@dataclass
class PullResult:
    revision: int
    updated: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


def _local_path(dotrix_dir: Path, rel: str) -> Path:
    # Platform paths are validated server-side; check again before touching disk.
    pure = PurePosixPath(rel)
    if pure.is_absolute() or ".." in pure.parts or any(p.startswith(".") for p in pure.parts):
        raise PlatformError(0, "invalid_path", f"Refusing to write unexpected path {rel!r}")
    return dotrix_dir.joinpath(*pure.parts)


def pull(client: PlatformClient, state: LinkState, dotrix_dir: str | Path, *, force: bool = False) -> PullResult:
    root = Path(dotrix_dir)
    first = not state.files
    params = {} if first else {"since_revision": state.revision}
    manifest = client.get(state.knowledge_path, params=params)
    result = PullResult(revision=manifest["revision"])

    for entry in manifest["files"]:
        rel = entry["path"]
        local = _local_path(root, rel)
        local_hash = _sha256(local.read_bytes()) if local.is_file() else None
        recorded = state.files.get(rel)
        # Edited locally since we last wrote it (or an unknown local file at that path).
        edited = local_hash is not None and local_hash != (recorded or entry["content_hash"])

        if entry["deleted"]:
            if local_hash is None:
                state.files.pop(rel, None)
            elif edited and not force:
                result.conflicts.append(rel)
            else:
                local.unlink()
                state.files.pop(rel, None)
                result.deleted.append(rel)
            continue

        if local_hash == entry["content_hash"]:
            state.files[rel] = local_hash
            continue
        if edited and not force:
            result.conflicts.append(rel)
            continue
        content = client.get(f"{state.knowledge_path}/files/{rel}")["content"]
        data = content.encode("utf-8")
        local.parent.mkdir(parents=True, exist_ok=True)
        tmp = local.with_name(local.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, local)
        state.files[rel] = _sha256(data)
        result.updated.append(rel)

    if not result.conflicts:
        state.revision = result.revision
    state.save(root)
    return result


def find_workspace(client: PlatformClient, ref: str) -> dict:
    workspaces = client.get("/workspaces")
    for ws in workspaces:
        if ref in (ws["id"], ws["slug"]) or ref.lower() == ws["name"].lower():
            return ws
    names = ", ".join(f"{w['slug']} ({w['name']})" for w in workspaces) or "none"
    raise PlatformError(404, "not_found", f"No workspace {ref!r}. Yours: {names}")


def find_project(client: PlatformClient, workspace_id: str, key: str) -> dict:
    projects = client.get(f"/workspaces/{workspace_id}/projects")
    for project in projects:
        if project["key"] == key.upper() or project["id"] == key:
            return project
    keys = ", ".join(p["key"] for p in projects) or "none"
    raise PlatformError(404, "not_found", f"No project {key!r} in that workspace. Projects: {keys}")


def follow_move(client: PlatformClient, state: LinkState, dotrix_dir: str | Path) -> str | None:
    """If the linked project was moved to another workspace, find it there by its id (which
    never changes) and update the link. Returns the new workspace's name when it moved."""
    try:
        client.get(f"/workspaces/{state.workspace_id}/projects/{state.project_id}")
        return None
    except PlatformError as exc:
        if exc.status != 404:
            raise
    for ws in client.get("/workspaces"):
        if ws["id"] == state.workspace_id:
            continue
        project = next((p for p in client.get(f"/workspaces/{ws['id']}/projects") if p["id"] == state.project_id), None)
        if project is not None:
            state.workspace_id = ws["id"]
            state.project_key, state.project_name = project["key"], project["name"]
            state.save(dotrix_dir)
            return ws["name"]
    return None  # gone, or moved somewhere you can't see: the command's own call says so
