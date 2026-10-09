"""People's own touches to the workspace's agents (decided 2026-10-09): extra instructions and a
model, for the runs each person starts. The contract (tools, folder access, issue types, what it
may do without asking) stays the workspace's, so a preference never widens what an agent may do.
Automations don't use them: they run as the workspace set them up.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core.errors import Forbidden, NotFound, Unprocessable
from pmagent_backend.modules.model_keys.service import may_choose
from pmagent_backend.modules.workspaces.models import Membership
from pmagent_engine.contracts import AgentSpec

from .models import AgentPreference
from .repository import AgentDefinitionRepository
from .schemas import AgentPreferenceRead, AgentPreferenceSave


def _read(row: AgentPreference) -> AgentPreferenceRead:
    return AgentPreferenceRead(handle=row.handle, instructions=row.instructions, model=row.model, updated_at=row.updated_at)


class AgentPreferences:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _row(self, member: Membership, handle: str) -> AgentPreference | None:
        return await self.session.scalar(select(AgentPreference).where(
            AgentPreference.workspace_id == member.workspace_id, AgentPreference.user_id == member.user_id,
            AgentPreference.handle == handle,
        ))

    async def list(self, member: Membership) -> list[AgentPreferenceRead]:
        rows = await self.session.scalars(select(AgentPreference).where(
            AgentPreference.workspace_id == member.workspace_id, AgentPreference.user_id == member.user_id,
        ).order_by(AgentPreference.handle))
        return [_read(row) for row in rows]

    async def save(
        self, member: Membership, handle: str, data: AgentPreferenceSave, *, available: list[str], personal: set[str]
    ) -> AgentPreferenceRead:
        handles = {a.spec.handle for a in await AgentDefinitionRepository(self.session).resolve(member.workspace_id)}
        if handle not in handles:
            raise NotFound(f"No agent @{handle} here")
        if data.model is not None:
            if data.model not in available:
                raise Unprocessable(f"{data.model} can't run here; choose one of: {', '.join(available) or 'none'}")
            if not may_choose(member, data.model, personal):
                raise Forbidden("Choosing a model needs the workspace's permission, unless it runs on your own key")
        row = await self._row(member, handle)
        if not data.instructions.strip() and data.model is None:
            if row is not None:
                await self.session.delete(row)
                await self.session.commit()
            return AgentPreferenceRead(handle=handle)
        if row is None:
            row = AgentPreference(workspace_id=member.workspace_id, user_id=member.user_id, handle=handle)
            self.session.add(row)
        row.instructions, row.model = data.instructions.strip(), data.model
        await self.session.commit()
        await self.session.refresh(row)
        return _read(row)

    async def remove(self, member: Membership, handle: str) -> None:
        row = await self._row(member, handle)
        if row is None:
            raise NotFound(f"You have no preferences for @{handle}")
        await self.session.delete(row)
        await self.session.commit()


async def preferences_for(session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, AgentPreference]:
    rows = await session.scalars(select(AgentPreference).where(
        AgentPreference.workspace_id == workspace_id, AgentPreference.user_id == user_id,
    ))
    return {row.handle: row for row in rows}


def with_preferences(specs: list[AgentSpec], prefs: dict[str, AgentPreference], person: str) -> list[AgentSpec]:
    """Each agent with the person's model and their instructions added after its own. The text
    is the person's (they're who the agent works for), framed so it can't widen what it may do."""
    out = []
    for spec in specs:
        pref = prefs.get(spec.handle)
        if pref is None:
            out.append(spec)
            continue
        update: dict = {}
        if pref.model:
            update["model"] = pref.model
        if pref.instructions:
            update["instructions"] = (
                f"{spec.instructions}\n\n## How {person} likes you to work\n"
                "Their own preferences for the work they ask you for. They never change what you may "
                f"do, read, or change.\n\n{pref.instructions}"
            )
        out.append(spec.model_copy(update=update))
    return out
