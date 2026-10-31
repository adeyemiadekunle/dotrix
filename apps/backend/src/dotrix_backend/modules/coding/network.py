"""Sandbox network: the hosts Kai's sandboxes may reach besides the model API.

Owners and admins set them (`Permission.MANAGE_WORKSPACE`, never granted to members), for the workspace
and on top of that per project: named presets (package registries) and custom hosts, exact
(`api.example.com`) or a wildcard for one domain's hosts (`*.example.com`). Every change is audited.
A turn's sandbox gets the workspace's and its project's hosts with the model API (the Docker Cloud
sandbox's network policy, or the Docker sandbox's egress proxy); a sandbox opened with another list
isn't reused (`network_digest` is part of what the warm and sleeping sandboxes are matched on).

Each allowed host is somewhere the agent could send data, so on Docker Cloud the model key stays out
of the sandbox (a Docker secret) whenever any are allowed; see docker_cloud.py.
"""
from __future__ import annotations

import hashlib
import ipaddress
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.errors import Conflict
from dotrix_backend.modules.audit.models import AuthorType
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.projects.models import Project
from dotrix_backend.modules.workspaces.models import Membership, Workspace

from .schemas import SandboxNetworkRead, SandboxNetworkUpdate

PRESETS: dict[str, tuple[str, list[str]]] = {
    "npm": ("npm (and pnpm, Yarn)", ["registry.npmjs.org", "registry.yarnpkg.com"]),
    "pypi": ("PyPI (pip, uv)", ["pypi.org", "files.pythonhosted.org"]),
    "go": ("Go modules", ["proxy.golang.org", "sum.golang.org"]),
    "crates": ("crates.io (Cargo)", ["crates.io", "index.crates.io", "static.crates.io"]),
    "rubygems": ("RubyGems", ["rubygems.org", "index.rubygems.org"]),
    "maven": ("Maven Central", ["repo.maven.apache.org", "repo1.maven.org"]),
}
MAX_HOSTS = 50
_LABEL = r"(?!-)[a-z0-9-]{1,63}(?<!-)"
HOST = re.compile(rf"^(\*\.)?{_LABEL}(\.{_LABEL})+$")


def clean_hosts(values: list[str]) -> list[str]:
    """Hosts as stored: lowercase, deduplicated, each an exact name or `*.domain`; no schemes, ports,
    paths or IP addresses (a sandbox reaches names). Raises Conflict naming the first bad one."""
    hosts: list[str] = []
    for raw in values:
        host = raw.strip().lower().rstrip(".")
        if not host:
            continue
        try:
            ipaddress.ip_address(host)
            raise Conflict(f"{raw!r}: allow a host name, not an IP address")
        except ValueError:
            pass
        if not HOST.match(host) or host.startswith("*.") and host.count(".") < 2:
            raise Conflict(f"{raw!r} isn't a host name like api.example.com or *.example.com")
        if host not in hosts:
            hosts.append(host)
    if len(hosts) > MAX_HOSTS:
        raise Conflict(f"At most {MAX_HOSTS} hosts")
    return hosts


def _parts(stored: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    stored = stored or {}
    return ([p for p in stored.get("presets") or [] if p in PRESETS], list(stored.get("hosts") or []))


def expand(stored: dict[str, Any] | None) -> list[str]:
    presets, hosts = _parts(stored)
    out: list[str] = []
    for host in [h for p in presets for h in PRESETS[p][1]] + hosts:
        if host not in out:
            out.append(host)
    return out


def allowed_hosts(workspace: Workspace | None, project: Project | None) -> list[str]:
    """What a turn's sandbox may reach besides the model API: the workspace's hosts, then the project's."""
    out = expand(workspace.sandbox_network if workspace else None)
    return out + [h for h in expand(project.sandbox_network if project else None) if h not in out]


def network_digest(hosts: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(hosts)).encode()).hexdigest()[:16]


def _read(stored: dict[str, Any] | None, effective: list[str]) -> SandboxNetworkRead:
    presets, hosts = _parts(stored)
    return SandboxNetworkRead(
        presets=presets, hosts=hosts, effective=effective,
        available_presets={key: {"label": label, "hosts": list(found)} for key, (label, found) in PRESETS.items()},
    )


class SandboxNetwork:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def workspace(self, member: Membership) -> SandboxNetworkRead:
        workspace = await self.session.get(Workspace, member.workspace_id)
        return _read(workspace.sandbox_network if workspace else None, allowed_hosts(workspace, None))

    async def project(self, member: Membership, project: Project) -> SandboxNetworkRead:
        workspace = await self.session.get(Workspace, member.workspace_id)
        return _read(project.sandbox_network, allowed_hosts(workspace, project))

    async def set_workspace(self, member: Membership, data: SandboxNetworkUpdate) -> SandboxNetworkRead:
        workspace = await self.session.get(Workspace, member.workspace_id, with_for_update=True)
        assert workspace is not None
        before = expand(workspace.sandbox_network)
        workspace.sandbox_network = self._stored(data)
        self._audit(member, None, before, expand(workspace.sandbox_network))
        await self.session.commit()
        return await self.workspace(member)

    async def set_project(self, member: Membership, project: Project, data: SandboxNetworkUpdate) -> SandboxNetworkRead:
        before = expand(project.sandbox_network)
        project.sandbox_network = self._stored(data)
        self._audit(member, project, before, expand(project.sandbox_network))
        await self.session.commit()
        return await self.project(member, project)

    @staticmethod
    def _stored(data: SandboxNetworkUpdate) -> dict[str, Any] | None:
        unknown = [p for p in data.presets if p not in PRESETS]
        if unknown:
            raise Conflict(f"Unknown preset: {unknown[0]}")
        stored = {"presets": sorted(set(data.presets)), "hosts": clean_hosts(data.hosts)}
        return stored if stored["presets"] or stored["hosts"] else None

    def _audit(self, member: Membership, project: Project | None, before: list[str], after: list[str]) -> None:
        if before == after:
            return
        AuditLog(self.session).record(
            workspace_id=member.workspace_id, project_id=project.id if project else None,
            action="sandbox_network.updated", target=str(project.id if project else member.workspace_id),
            actor_type=AuthorType.USER, actor_user_id=member.user_id,
            details={"scope": "project" if project else "workspace",
                     "added": [h for h in after if h not in before], "removed": [h for h in before if h not in after]},
        )
