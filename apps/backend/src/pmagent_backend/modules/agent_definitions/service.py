"""Create, change, reset, and restore agents (docs/agents-v2.md §4.2, §4.8).

Changes are owners' and admins' (the routes check it); only owners may let an agent act without
asking (decided D1). Every save is a new version and an audit event naming what changed.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from pmagent_backend.modules.audit.service import AuditLog
from pmagent_backend.modules.knowledge.models import AuthorType
from pmagent_backend.modules.workspaces.models import Membership, Role
from pmagent_engine import catalog
from pmagent_engine.builtins import builtin
from pmagent_engine.contracts import RESERVED_HANDLES, AgentSpec
from pmagent_engine.permissions import ISSUE_TYPES, Access

from .models import AgentDefinition, AgentDefinitionVersion
from .repository import AgentDefinitionRepository, ResolvedAgent
from .schemas import AgentCatalog, AgentFields, AgentRead, AgentSave, AgentVersionRead, ToolOption


class AgentChanged(Conflict):
    code = "agent_changed"


class InvalidAgent(Unprocessable):
    code = "invalid_agent"


class AgentModelNotAvailable(Unprocessable):
    code = "model_not_available"


def _now() -> datetime:
    return datetime.now(UTC)


def _fields(spec: AgentSpec) -> AgentFields:
    return AgentFields.model_validate(spec.model_dump(exclude={"handle", "base"}))


def _read(agent: ResolvedAgent) -> AgentRead:
    return AgentRead(
        **_fields(agent.spec).model_dump(),
        handle=agent.spec.handle,
        base=agent.spec.base,
        source=agent.source,
        scope=agent.scope,
        version=agent.version,
        updated_at=agent.updated_at,
    )


def _allowed(spec: AgentSpec | None) -> set[str]:
    return {action for action, rule in (spec.autonomy if spec else {}).items() if rule == "allow"}


def catalog_read() -> AgentCatalog:
    return AgentCatalog(
        tools=[ToolOption(id=g.id, label=g.label, description=g.description, actions=list(g.actions))
               for g in catalog.CATALOG],
        actions=list(catalog.ACTIONS),
        low_risk_actions=sorted(catalog.LOW_RISK_ACTIONS),
        access_levels=list(Access),
        issue_types=list(ISSUE_TYPES),
        reserved_handles=sorted(RESERVED_HANDLES),
    )


class AgentDefinitionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AgentDefinitionRepository(session)

    async def list(self, workspace_id: uuid.UUID, project_id: uuid.UUID | None = None) -> list[AgentRead]:
        return [_read(agent) for agent in await self.repo.resolve(workspace_id, project_id)]

    async def get(self, workspace_id: uuid.UUID, project_id: uuid.UUID | None, handle: str) -> AgentRead:
        return _read(await self._resolved(workspace_id, project_id, handle))

    async def save(
        self,
        member: Membership,
        project_id: uuid.UUID | None,
        handle: str,
        data: AgentSave,
        *,
        available_models: list[str] | None = None,
        note: str | None = None,
    ) -> AgentRead:
        """Create a custom agent, or change one (a built-in's first change creates its definition)."""
        workspace_id = member.workspace_id
        base = builtin(handle)
        if handle == "auto" or (base is None and handle in RESERVED_HANDLES):
            raise InvalidAgent(f"{handle!r} is reserved; choose another handle")
        try:
            spec = AgentSpec.model_validate(
                data.agent.model_dump() | {"handle": handle, "base": handle if base else None}
            )
        except ValidationError as exc:
            raise InvalidAgent("; ".join(_messages(exc))) from exc
        if spec.model and available_models is not None and spec.model not in available_models:
            raise AgentModelNotAvailable(
                f"{spec.model} can't run here; choose one of: {', '.join(available_models) or 'none'}"
            )

        definition = await self.repo.get(workspace_id, project_id, handle, for_update=True)
        live = definition is not None and definition.archived_at is None
        if live and data.base_version != definition.current_version:
            raise AgentChanged(
                f"{handle} changed since you opened it (now version {definition.current_version}); reload and try again"
            )
        current = await self._find(workspace_id, project_id, handle)
        previous = current.spec if current else None
        if (_allowed(spec) - _allowed(previous)) and member.role is not Role.OWNER:
            raise Forbidden("Only owners can let an agent act without asking")
        if live and previous is not None and previous == spec:
            return await self.get(workspace_id, project_id, handle)  # nothing changed

        now = _now()
        if definition is None:
            definition = AgentDefinition(
                workspace_id=workspace_id, project_id=project_id, handle=handle,
                base=spec.base, current_version=1, created_by_id=member.user_id,
            )
            self.session.add(definition)
            await self.session.flush()
            action = "agent.customised" if base else "agent.created"
        else:
            action = "agent.updated" if live else ("agent.customised" if base else "agent.created")
            definition.current_version += 1
            definition.archived_at = None
            definition.updated_at = now
        self.session.add(
            AgentDefinitionVersion(
                workspace_id=workspace_id, definition_id=definition.id, version=definition.current_version,
                spec=spec.model_dump(mode="json", exclude={"handle"}), note=note or data.note,
                author_user_id=member.user_id, created_at=now,
            )
        )
        changed = sorted(
            field for field in AgentFields.model_fields
            if previous is None or getattr(previous, field) != getattr(spec, field)
        )
        self._audit(member, project_id, action, handle, version=definition.current_version, changed=changed)
        await self.session.commit()
        return await self.get(workspace_id, project_id, handle)

    async def delete(self, member: Membership, project_id: uuid.UUID | None, handle: str) -> None:
        """Remove a custom agent, reset a built-in to its default, or drop a project's override."""
        definition = await self.repo.get(member.workspace_id, project_id, handle, for_update=True)
        if definition is None or definition.archived_at is not None:
            raise NotFound(f"{handle} has no changes here to remove")
        definition.archived_at = _now()
        action = "agent.reset" if definition.base else "agent.removed"
        self._audit(member, project_id, action, handle, version=definition.current_version)
        await self.session.commit()

    async def versions(self, workspace_id: uuid.UUID, project_id: uuid.UUID | None, handle: str) -> list[AgentVersionRead]:
        definition = await self._definition(workspace_id, project_id, handle)
        return [
            AgentVersionRead(
                version=v.version,
                agent=_fields(AgentSpec.model_validate(v.spec | {"handle": handle})),
                note=v.note,
                author_user_id=str(v.author_user_id) if v.author_user_id else None,
                created_at=v.created_at,
            )
            for v in await self.repo.versions(definition)
        ]

    async def restore(
        self, member: Membership, project_id: uuid.UUID | None, handle: str, version: int,
        *, available_models: list[str] | None = None,
    ) -> AgentRead:
        """Save an earlier version as the new current one."""
        definition = await self._definition(member.workspace_id, project_id, handle)
        old = await self.repo.version(definition, version)
        if old is None:
            raise NotFound(f"{handle} has no version {version}")
        fields = AgentFields.model_validate({k: v for k, v in old.spec.items() if k in AgentFields.model_fields})
        base_version = definition.current_version if definition.archived_at is None else None
        return await self.save(
            member, project_id, handle, AgentSave(agent=fields, base_version=base_version),
            available_models=available_models, note=f"Restored version {version}",
        )

    # -- helpers ---------------------------------------------------------------------------

    async def _find(self, workspace_id: uuid.UUID, project_id: uuid.UUID | None, handle: str) -> ResolvedAgent | None:
        return next((a for a in await self.repo.resolve(workspace_id, project_id) if a.spec.handle == handle), None)

    async def _resolved(self, workspace_id: uuid.UUID, project_id: uuid.UUID | None, handle: str) -> ResolvedAgent:
        agent = await self._find(workspace_id, project_id, handle)
        if agent is None:
            raise NotFound(f"No agent @{handle}")
        return agent

    async def _definition(self, workspace_id: uuid.UUID, project_id: uuid.UUID | None, handle: str) -> AgentDefinition:
        definition = await self.repo.get(workspace_id, project_id, handle)
        if definition is None:
            raise NotFound(f"{handle} has no saved versions here")
        return definition

    def _audit(
        self, member: Membership, project_id: uuid.UUID | None, action: str, handle: str, **details: object
    ) -> None:
        AuditLog(self.session).record(
            workspace_id=member.workspace_id,
            project_id=project_id,
            action=action,
            target=f"@{handle}",
            actor_type=AuthorType.USER,
            actor_user_id=member.user_id,
            details={**details, "scope": "project" if project_id else "workspace"},
        )


def _messages(exc: ValidationError) -> list[str]:
    out = []
    for error in exc.errors():
        where = ".".join(str(part) for part in error.get("loc", ()) if part != "__root__")
        message = str(error.get("msg", "")).removeprefix("Value error, ")
        out.append(f"{where}: {message}" if where else message)
    return out
