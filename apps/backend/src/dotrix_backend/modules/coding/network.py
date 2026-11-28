"""Network policy: the hosts Kai's sandboxes may reach besides the model API.

One policy in three layers, in one format (`dotrix_engine/network_policy.py`, shared with the local runner):

- The workspace's limit (`workspaces.sandbox_network`; None is no limit). Owners and admins set it
  (`Permission.MANAGE_WORKSPACE`, never granted to members): the most any project may allow.
- The project's choice (`projects.sandbox_network`), within the limit: named presets (package registries) and hosts,
  exact (`api.example.com`), a wildcard for one domain's hosts (`*.example.com`) or either on a port
  (`registry.example.com:8443`). Settings → Environments shows it with the project's environment.
- The coding session's pin (`coding_runs.network_snapshot`): the project's choice when the session's first turn was
  admitted, kept by every follow-up, cloud or local, as its environment is. A project's later edits apply to new
  sessions. The limit as it is now still applies to every turn (`for_run`), so lowering it takes effect at once.

Every change is audited. A turn's sandbox gets its list with the model API (the Docker Cloud sandbox's network policy;
OpenShell's sandbox policy, sandbox.py); a local runner gets it in its claim and may
only narrow it (dotrix_cli/network_allow.py). A sandbox opened with another list isn't reused (`network_digest` is part
of what warm and sleeping sandboxes are matched on).

Each allowed host is somewhere the agent could send data, so on Docker Cloud the model key stays out of the sandbox
(a Docker secret) whenever any are allowed; see docker_cloud.py.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.errors import Conflict
from dotrix_backend.modules.audit.models import AuthorType
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.projects.models import Project
from dotrix_backend.modules.workspaces.models import Membership, Workspace
from dotrix_engine import network_policy
from dotrix_engine.network_policy import PRESETS, InvalidEntry

from .schemas import SandboxNetworkLimitUpdate, SandboxNetworkRead, SandboxNetworkUpdate

MAX_HOSTS = network_policy.MAX_ENTRIES


def clean_hosts(values: list[str]) -> list[str]:
    """Entries as stored (network_policy.clean). Raises Conflict naming the first bad one."""
    try:
        return network_policy.clean(values)
    except InvalidEntry as exc:
        raise Conflict(str(exc)) from exc


def _parts(stored: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    stored = stored or {}
    return ([p for p in stored.get("presets") or [] if p in PRESETS], list(stored.get("hosts") or []))


def expand(stored: dict[str, Any] | None) -> list[str]:
    return network_policy.expand(*_parts(stored))


def limit_of(workspace: Workspace | None) -> list[str] | None:
    """The most any project in the workspace may allow, or None: no limit."""
    if workspace is None or workspace.sandbox_network is None:
        return None
    return expand(workspace.sandbox_network)


def allowed_hosts(workspace: Workspace | None, project: Project | None) -> list[str]:
    """What a new session in the project pins: the project's choice, as far as the workspace's limit allows."""
    return network_policy.narrow(expand(project.sandbox_network if project else None), limit_of(workspace))


def for_run(workspace: Workspace | None, project: Project | None, pinned: list[str] | None) -> list[str]:
    """What a turn's sandbox may reach: its session's pinned list (a run from before pins: the project's choice now),
    as far as the workspace's limit allows now."""
    chosen = list(pinned) if pinned is not None else expand(project.sandbox_network if project else None)
    return network_policy.narrow(chosen, limit_of(workspace))


def network_digest(hosts: list[str]) -> str:
    return network_policy.digest(hosts)


def _presets() -> dict[str, dict[str, Any]]:
    return {key: {"label": label, "hosts": list(found)} for key, (label, found) in PRESETS.items()}


class SandboxNetwork:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def workspace(self, member: Membership) -> SandboxNetworkRead:
        workspace = await self.session.get(Workspace, member.workspace_id)
        limit = limit_of(workspace)
        presets, hosts = _parts(workspace.sandbox_network if workspace else None)
        return SandboxNetworkRead(presets=presets, hosts=hosts, effective=limit or [], limited=limit is not None,
                                  limit=limit, outside_limit=[], available_presets=_presets())

    async def project(self, member: Membership, project: Project) -> SandboxNetworkRead:
        workspace = await self.session.get(Workspace, member.workspace_id)
        limit, chosen = limit_of(workspace), expand(project.sandbox_network)
        presets, hosts = _parts(project.sandbox_network)
        effective = network_policy.narrow(chosen, limit)
        return SandboxNetworkRead(presets=presets, hosts=hosts, effective=effective, limited=limit is not None,
                                  limit=limit, outside_limit=[h for h in chosen if h not in effective],
                                  available_presets=_presets())

    async def set_workspace(self, member: Membership, data: SandboxNetworkLimitUpdate) -> SandboxNetworkRead:
        workspace = await self.session.get(Workspace, member.workspace_id, with_for_update=True)
        assert workspace is not None
        if not data.limited and (data.presets or data.hosts):
            raise Conflict("Turn the workspace limit on to list hosts; each project chooses its own hosts")
        before = limit_of(workspace)
        workspace.sandbox_network = {"presets": [], "hosts": []} | (self._stored(data) or {}) if data.limited else None
        after = limit_of(workspace)
        if before != after:
            self._record(member, None, {"scope": "workspace", "limited": after is not None,
                                        "added": [h for h in after or [] if h not in (before or [])],
                                        "removed": [h for h in before or [] if h not in (after or [])]})
        await self.session.commit()
        return await self.workspace(member)

    async def set_project(self, member: Membership, project: Project, data: SandboxNetworkUpdate) -> SandboxNetworkRead:
        self.change_project(member, project, data, await self.session.get(Workspace, member.workspace_id))
        await self.session.commit()
        return await self.project(member, project)

    def change_project(self, member: Membership, project: Project, data: SandboxNetworkUpdate,
                       workspace: Workspace | None) -> None:
        """Set the project's network policy, within the workspace's limit, and audit it; the caller commits (the
        environment form saves it with the environment, in one transaction)."""
        stored = self._stored(data)
        limit = limit_of(workspace)
        outside = [h for h in expand(stored) if limit is not None and not network_policy.within(limit, h)]
        if outside:
            raise Conflict(f"{', '.join(outside)}: outside the network access limit for all projects; an owner or admin can widen it")
        before = expand(project.sandbox_network)
        project.sandbox_network = stored
        after = expand(project.sandbox_network)
        if before != after:
            self._record(member, project, {"scope": "project", "added": [h for h in after if h not in before],
                                           "removed": [h for h in before if h not in after]})

    @staticmethod
    def _stored(data: SandboxNetworkUpdate | SandboxNetworkLimitUpdate) -> dict[str, Any] | None:
        unknown = [p for p in data.presets if p not in PRESETS]
        if unknown:
            raise Conflict(f"Unknown preset: {unknown[0]}")
        stored = {"presets": sorted(set(data.presets)), "hosts": clean_hosts(data.hosts)}
        return stored if stored["presets"] or stored["hosts"] else None

    def _record(self, member: Membership, project: Project | None, details: dict[str, Any]) -> None:
        AuditLog(self.session).record(
            workspace_id=member.workspace_id, project_id=project.id if project else None,
            action="sandbox_network.updated", target=str(project.id if project else member.workspace_id),
            actor_type=AuthorType.USER, actor_user_id=member.user_id, details=details,
        )
