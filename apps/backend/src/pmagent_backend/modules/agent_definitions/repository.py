"""Which agents a workspace or project has: the built-ins, changed or not, plus custom agents.

Resolution for a project: its override, else the workspace's definition, else the built-in.
Used by the agent-definition routes and by every agent run.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_engine.builtins import builtin_specs
from pmagent_engine.contracts import AgentSpec

from .models import AgentDefinition, AgentDefinitionVersion

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedAgent:
    spec: AgentSpec
    source: str  # built_in, customised, custom
    scope: str  # default, workspace, project
    version: int | None
    updated_at: datetime | None


class AgentDefinitionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self, workspace_id: uuid.UUID, project_id: uuid.UUID | None, handle: str, *, for_update: bool = False
    ) -> AgentDefinition | None:
        stmt = select(AgentDefinition).where(
            AgentDefinition.workspace_id == workspace_id,
            AgentDefinition.handle == handle,
            AgentDefinition.project_id.is_(None) if project_id is None else AgentDefinition.project_id == project_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def version(self, definition: AgentDefinition, version: int | None = None) -> AgentDefinitionVersion | None:
        return await self.session.scalar(
            select(AgentDefinitionVersion).where(
                AgentDefinitionVersion.definition_id == definition.id,
                AgentDefinitionVersion.version == (version or definition.current_version),
            )
        )

    async def versions(self, definition: AgentDefinition) -> list[AgentDefinitionVersion]:
        return list(
            await self.session.scalars(
                select(AgentDefinitionVersion)
                .where(AgentDefinitionVersion.definition_id == definition.id)
                .order_by(AgentDefinitionVersion.version.desc())
            )
        )

    async def resolve(self, workspace_id: uuid.UUID, project_id: uuid.UUID | None = None) -> list[ResolvedAgent]:
        """The agents in effect: built-ins first (in their order), then custom agents by handle."""
        agents: dict[str, ResolvedAgent] = {
            spec.handle: ResolvedAgent(spec, "built_in", "default", None, None) for spec in builtin_specs()
        }
        builtin_handles = set(agents)
        scope_filter = AgentDefinition.project_id.is_(None)
        if project_id is not None:
            scope_filter = scope_filter | (AgentDefinition.project_id == project_id)
        rows = await self.session.execute(
            select(AgentDefinition, AgentDefinitionVersion)
            .join(
                AgentDefinitionVersion,
                (AgentDefinitionVersion.definition_id == AgentDefinition.id)
                & (AgentDefinitionVersion.version == AgentDefinition.current_version),
            )
            .where(AgentDefinition.workspace_id == workspace_id, AgentDefinition.archived_at.is_(None), scope_filter)
            # Workspace definitions first, so a project's override replaces them.
            .order_by(AgentDefinition.project_id.is_not(None), AgentDefinition.handle)
        )
        for definition, version in rows:
            try:
                spec = AgentSpec.model_validate(version.spec | {"handle": definition.handle})
            except ValidationError:
                # Stored under older rules that no longer validate: fall back to what was there.
                logger.warning("agent definition %s v%s no longer validates", definition.id, version.version)
                continue
            agents[definition.handle] = ResolvedAgent(
                spec,
                "customised" if definition.handle in builtin_handles else "custom",
                "project" if definition.project_id else "workspace",
                definition.current_version,
                definition.updated_at,
            )
        return list(agents.values())

    async def specs(self, workspace_id: uuid.UUID, project_id: uuid.UUID) -> list[AgentSpec]:
        return [agent.spec for agent in await self.resolve(workspace_id, project_id)]
