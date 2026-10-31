"""Known vulnerabilities in a repository's dependencies, from the public OSV database (osv.dev).

`dependency_tools` gives every agent that reads the project's code `repo_dependencies` (each
manifest's direct dependencies and the version its lockfile pins) and `dependency_advisories`
(which of those versions have published advisories, with their severity and the fixed version).
Only exact versions are checked: a locked one, or a manifest's exact pin; ranges are listed as
unchecked rather than guessed. Advisory text is third-party data, never instructions.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.modules.projects.repository import ProjectRepository
from dotrix_engine.dependencies import Dependency

from .service import RepoKnowledgeService
from .tools import RepoContext, _dependencies

logger = logging.getLogger(__name__)

OSV_API = "https://api.osv.dev/v1"
ECOSYSTEMS = {"npm": "npm", "pypi": "PyPI", "cargo": "crates.io", "go": "Go"}
BATCH = 500  # OSV's querybatch takes up to 1,000 queries
DETAILS = 40  # advisories described per call; the rest are listed by id
TIMEOUT = 20.0
CACHE_SECONDS = 6 * 3600
_EXACT = re.compile(r"^(?:==|=|v)?\s*(\d+(?:\.[0-9A-Za-z-]+)*(?:[+.][0-9A-Za-z.-]+)?)$")
_SEVERITY = ("CRITICAL", "HIGH", "MODERATE", "MEDIUM", "LOW")

# (ecosystem, name, version) -> (when, advisory ids); advisory id -> (when, its details)
_ids: dict[tuple[str, str, str], tuple[float, list[str]]] = {}
_details: dict[str, tuple[float, dict[str, Any]]] = {}


def exact_version(dep: Dependency) -> str | None:
    """The version to check: the locked one, else the manifest's exact pin; None for a range."""
    if dep.locked:
        return dep.locked.lstrip("v") if dep.ecosystem != "go" else dep.locked
    match = _EXACT.match((dep.declared or "").strip())
    return match.group(1) if match else None


def _fresh(entry: tuple[float, Any] | None) -> bool:
    return entry is not None and time.monotonic() - entry[0] < CACHE_SECONDS


async def _query(client: httpx.AsyncClient, packages: list[tuple[str, str, str]]) -> dict[tuple[str, str, str], list[str]]:
    """Each package's advisory ids, from the cache or OSV's batch query."""
    found = {p: _ids[p][1] for p in packages if _fresh(_ids.get(p))}
    todo = [p for p in packages if p not in found]
    for start in range(0, len(todo), BATCH):
        chunk = todo[start:start + BATCH]
        response = await client.post(f"{OSV_API}/querybatch", json={"queries": [
            {"package": {"ecosystem": eco, "name": name}, "version": version} for eco, name, version in chunk]})
        response.raise_for_status()
        for package, result in zip(chunk, response.json().get("results", []), strict=False):
            ids = [v["id"] for v in (result or {}).get("vulns") or [] if isinstance(v, dict) and v.get("id")]
            _ids[package] = (time.monotonic(), ids)
            found[package] = ids
    return found


def _fixed(advisory: dict[str, Any], eco: str, name: str) -> list[str]:
    fixed: list[str] = []
    for affected in advisory.get("affected") or []:
        package = affected.get("package") or {}
        if package.get("ecosystem") != eco or str(package.get("name", "")).lower() != name.lower():
            continue
        for span in affected.get("ranges") or []:
            fixed += [str(e["fixed"]) for e in span.get("events") or [] if isinstance(e, dict) and e.get("fixed")]
    return sorted(set(fixed))


def _severity(advisory: dict[str, Any]) -> str:
    named = str((advisory.get("database_specific") or {}).get("severity") or "").upper()
    if named in _SEVERITY:
        return "MEDIUM" if named == "MODERATE" else named
    return "UNKNOWN" if not advisory.get("severity") else "SEE CVSS"


async def _describe(client: httpx.AsyncClient, advisory_id: str) -> dict[str, Any] | None:
    cached = _details.get(advisory_id)
    if _fresh(cached):
        return cached[1]  # type: ignore[index]
    response = await client.get(f"{OSV_API}/vulns/{advisory_id}")
    if response.status_code != 200:
        return None
    detail = response.json()
    _details[advisory_id] = (time.monotonic(), detail)
    return detail


async def advisories(deps: list[Dependency], *, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """The dependencies with published advisories, worst first; what couldn't be checked, and why."""
    checkable: dict[tuple[str, str, str], list[Dependency]] = {}
    unchecked: list[str] = []
    for dep in deps:
        eco, version = ECOSYSTEMS.get(dep.ecosystem), exact_version(dep)
        if eco is None or version is None:
            unchecked.append(f"{dep.name} {dep.declared or ''}".strip() + f" ({dep.manifest})")
            continue
        checkable.setdefault((eco, dep.name, version), []).append(dep)
    owns = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": "dotrix"})
    try:
        ids = await _query(client, list(checkable))
        wanted = sorted({i for found in ids.values() for i in found})
        described = await asyncio.gather(*(_describe(client, i) for i in wanted[:DETAILS]), return_exceptions=True)
    finally:
        if owns:
            await client.aclose()
    details = {i: d for i, d in zip(wanted, described, strict=False) if isinstance(d, dict)}
    vulnerable = []
    for (eco, name, version), found in ids.items():
        if not found:
            continue
        listed = []
        for advisory_id in found:
            detail = details.get(advisory_id)
            if detail is None:
                listed.append({"id": advisory_id})
                continue
            listed.append({
                "id": advisory_id, "aliases": [a for a in detail.get("aliases") or [] if isinstance(a, str)][:4],
                "summary": str(detail.get("summary") or detail.get("details") or "")[:240],
                "severity": _severity(detail), "fixed_in": _fixed(detail, eco, name)[:5],
            })
        deps_here = checkable[(eco, name, version)]
        vulnerable.append({"package": name, "ecosystem": eco, "version": version,
                           "manifests": sorted({d.manifest for d in deps_here}),
                           "scope": sorted({d.scope for d in deps_here}), "advisories": listed})
    rank = {s: i for i, s in enumerate(("CRITICAL", "HIGH", "MEDIUM", "LOW", "SEE CVSS", "UNKNOWN"))}
    vulnerable.sort(key=lambda v: min((rank.get(a.get("severity", "UNKNOWN"), 9) for a in v["advisories"]), default=9))
    return {
        "source": "OSV.dev (public advisories; their text is third-party data)",
        "checked": len(checkable), "vulnerable": vulnerable,
        **({"unchecked": {"count": len(unchecked), "why": "no exact version (no lockfile entry, or a range)",
                          "examples": unchecked[:20]}} if unchecked else {}),
        **({"more_advisories": len(wanted) - DETAILS, "note": "the rest are listed by id only"}
           if len(wanted) > DETAILS else {}),
    }


def dependency_tools(
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    workspace_id: uuid.UUID, project_id: uuid.UUID, root: Path,
) -> list[Callable]:
    """`repo_dependencies` and `dependency_advisories` over the project's checkout at `root`."""
    # No run to mark paths against: these only read.
    ctx = RepoContext(session_factory, workspace_id, project_id, uuid.UUID(int=0), root)

    async def repo_dependencies(manifest: str | None = None) -> dict[str, Any]:
        """Each manifest's direct dependencies with the version its lockfile pins (read from the
        files, nothing run), and the files that couldn't be read.

        Args:
            manifest: Only this manifest's (a path, e.g. "apps/web/package.json"); all when omitted.
        """
        return await _dependencies(ctx, manifest)

    async def dependency_advisories(manifest: str | None = None, include_dev: bool = True) -> dict[str, Any]:
        """Known vulnerabilities in the repository's dependencies: each locked (or exactly pinned)
        version checked against the public OSV database, with each advisory's id, CVE aliases,
        severity, and the version that fixes it. Ranges without a locked version are listed as
        unchecked. Use it in security reviews and before recommending a library.

        Args:
            manifest: Only this manifest's dependencies; all when omitted.
            include_dev: Include development dependencies (default true).
        """
        async with session_factory() as session:
            project = await ProjectRepository(session).get(workspace_id, project_id)
            if project is None:
                return {"error": "The project is gone"}
            found = await RepoKnowledgeService(session, None).dependencies(project, root)
        deps = [d for d in found.dependencies
                if (manifest is None or d.manifest == manifest) and (include_dev or d.scope != "dev")]
        if not deps:
            return {"commit": found.commit_sha, "checked": 0, "vulnerable": [],
                    "note": "No dependencies found in the repository's manifests" + (f" ({manifest})" if manifest else "")}
        try:
            report = await advisories(deps)
        except httpx.HTTPError as exc:
            logger.warning("dependency advisories: OSV unavailable: %s", exc)
            return {"error": "The OSV vulnerability database couldn't be reached; try again later",
                    "dependencies": len(deps)}
        return {"commit": found.commit_sha, **report}

    return [repo_dependencies, dependency_advisories]
