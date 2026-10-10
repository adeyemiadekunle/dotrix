"""Workspace rules: read, saved (versioned, audited), and layered under each project's rules."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.errors import Conflict, NotFound
from dotrix_backend.modules.agent_definitions.repository import AgentDefinitionRepository
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.knowledge.models import AuthorType
from dotrix_backend.modules.workspaces.models import Membership
from dotrix_engine.skills import describe_skill

from .models import WorkspaceRule, WorkspaceSkill
from .schemas import WorkspaceRuleRead, WorkspaceRuleSave, WorkspaceSkillRead

BASE = "base"


class RulesChanged(Conflict):
    code = "rules_changed"

AUDIT_CHARS = 20_000


class WorkspaceRules:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, workspace_id: uuid.UUID) -> list[WorkspaceRuleRead]:
        rows = await self.session.scalars(
            select(WorkspaceRule).where(WorkspaceRule.workspace_id == workspace_id, WorkspaceRule.content != "")
            .order_by(WorkspaceRule.handle != BASE, WorkspaceRule.handle)
        )
        return [WorkspaceRuleRead.model_validate(r) for r in rows]

    async def texts(self, workspace_id: uuid.UUID) -> dict[str, str]:
        """For a run: handle -> the workspace's rule text."""
        return {r.handle: r.content for r in await self.list(workspace_id)}

    async def save(self, member: Membership, handle: str, data: WorkspaceRuleSave) -> WorkspaceRuleRead:
        if handle != BASE:
            known = {a.spec.handle for a in await AgentDefinitionRepository(self.session).resolve(member.workspace_id)}
            if handle not in known:
                raise NotFound(f"No agent @{handle} in this workspace")
        row = await self.session.scalar(
            select(WorkspaceRule).where(WorkspaceRule.workspace_id == member.workspace_id, WorkspaceRule.handle == handle)
            .with_for_update()
        )
        current = row.version if row is not None else 0
        if data.base_version != current:
            raise RulesChanged(f"These rules changed since (version {current}); reload and apply your change again")
        content = data.content.strip()
        before = row.content if row is not None else ""
        if row is None:
            row = WorkspaceRule(workspace_id=member.workspace_id, handle=handle, content="", version=0)
            self.session.add(row)
        if content == before:
            return WorkspaceRuleRead.model_validate(row) if row.version else _empty(handle)
        row.content, row.version = content, current + 1
        row.updated_by_id, row.updated_at = member.user_id, datetime.now(UTC)
        AuditLog(self.session).record(
            workspace_id=member.workspace_id, action="workspace_rules.saved", target=handle,
            actor_type=AuthorType.USER, actor_user_id=member.user_id,
            details={"version": row.version, "before": before[:AUDIT_CHARS], "removed": not content},
        )
        await self.session.commit()
        return WorkspaceRuleRead.model_validate(row)


def _empty(handle: str) -> WorkspaceRuleRead:
    return WorkspaceRuleRead(handle=handle, content="", version=0, updated_by_id=None, updated_at=datetime.now(UTC))


def layered(workspace: dict[str, str], project: dict[str, str]) -> dict[str, str]:
    """The workspace's rules first, then the project's, per handle: the more specific comes
    last, so it wins where they differ."""
    merged = dict(project)
    for handle, text in workspace.items():
        merged[handle] = f"## Rules for every project in this workspace\n{text}\n\n{project.get(handle, '')}".strip()
    return merged


class SkillChanged(Conflict):
    code = "skill_changed"


def skill_read(row: WorkspaceSkill) -> WorkspaceSkillRead:
    return WorkspaceSkillRead(
        name=row.name, description=describe_skill(row.content), content=row.content, version=row.version,
        updated_by_id=row.updated_by_id, updated_at=row.updated_at,
    )


class WorkspaceSkills:
    """Skills shared by every project in the workspace."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, workspace_id: uuid.UUID) -> list[WorkspaceSkillRead]:
        rows = await self.session.scalars(
            select(WorkspaceSkill).where(WorkspaceSkill.workspace_id == workspace_id, WorkspaceSkill.content != "")
            .order_by(WorkspaceSkill.name)
        )
        return [skill_read(r) for r in rows]

    async def texts(self, workspace_id: uuid.UUID) -> dict[str, str]:
        return {s.name: s.content for s in await self.list(workspace_id)}

    async def get(self, workspace_id: uuid.UUID, name: str) -> str | None:
        return await self.session.scalar(
            select(WorkspaceSkill.content).where(
                WorkspaceSkill.workspace_id == workspace_id, WorkspaceSkill.name == name, WorkspaceSkill.content != ""
            )
        )

    async def save(self, member: Membership, name: str, data: WorkspaceRuleSave) -> WorkspaceSkillRead:
        row = await self.session.scalar(
            select(WorkspaceSkill).where(WorkspaceSkill.workspace_id == member.workspace_id, WorkspaceSkill.name == name)
            .with_for_update()
        )
        current = row.version if row is not None else 0
        if data.base_version != current:
            raise SkillChanged(f"This skill changed since (version {current}); reload and apply your change again")
        content = data.content.strip()
        before = row.content if row is not None else ""
        if row is None:
            row = WorkspaceSkill(workspace_id=member.workspace_id, name=name, content="", version=0,
                                 updated_at=datetime.now(UTC))
            self.session.add(row)
        if content != before:
            row.content, row.version = content, current + 1
            row.updated_by_id, row.updated_at = member.user_id, datetime.now(UTC)
            AuditLog(self.session).record(
                workspace_id=member.workspace_id, action="workspace_skill.saved", target=name,
                actor_type=AuthorType.USER, actor_user_id=member.user_id,
                details={"version": row.version, "before": before[:AUDIT_CHARS], "removed": not content},
            )
            await self.session.commit()
        return skill_read(row)
