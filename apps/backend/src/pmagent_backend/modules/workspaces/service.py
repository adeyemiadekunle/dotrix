from __future__ import annotations

import re
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core.errors import Conflict, Forbidden, NotFound
from pmagent_backend.modules.audit.service import AuditLog
from pmagent_backend.modules.auth.models import User, UserAvatar
from pmagent_backend.modules.auth.profile import ProfileService
from pmagent_backend.modules.auth.repository import UserRepository
from pmagent_backend.modules.knowledge.models import AuthorType
from pmagent_backend.modules.projects.models import ProjectAccessLevel, ProjectMember
from pmagent_backend.modules.projects.repository import ProjectRepository

from .models import Membership, Role, Workspace, WorkspaceKind
from .permissions import Permission, can
from .repository import MembershipRepository, WorkspaceRepository
from .schemas import (
    MemberRead,
    OrganizationConversion,
    WorkspaceCreate,
    WorkspaceUpdate,
    WorkspaceWithRole,
)


def make_slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "workspace"
    return f"{base}-{secrets.token_hex(3)}"


class WorkspaceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.workspaces = WorkspaceRepository(session)
        self.members = MembershipRepository(session)

    async def _audit(
        self, actor: Membership, action: str, target_user_id: uuid.UUID | None = None, **details: object
    ) -> None:
        """Record a people or settings change in the workspace's audit log (same transaction)."""
        target = None
        if target_user_id is not None:
            user = await UserRepository(self.session).get(target_user_id)
            target = user.email if user else str(target_user_id)
            details["user_id"] = str(target_user_id)
        AuditLog(self.session).record(
            workspace_id=actor.workspace_id,
            action=action,
            target=target,
            actor_type=AuthorType.USER,
            actor_user_id=actor.user_id,
            details=details,
        )

    def _create(self, name: str, kind: WorkspaceKind, owner: User) -> Workspace:
        workspace = Workspace(
            name=name,
            slug=make_slug(name),
            kind=kind,
            created_by_id=owner.id,
        )
        self.workspaces.add(workspace)
        return workspace

    async def create_personal(self, owner: User) -> Workspace:
        """Called during sign-up; the caller commits."""
        workspace = self._create("Personal", WorkspaceKind.PERSONAL, owner)
        await self.session.flush()
        self.members.add(Membership(workspace_id=workspace.id, user_id=owner.id, role=Role.OWNER))
        return workspace

    async def create(self, owner: User, data: WorkspaceCreate) -> WorkspaceWithRole:
        workspace = self._create(data.name, data.kind, owner)
        await self.session.flush()
        self.members.add(Membership(workspace_id=workspace.id, user_id=owner.id, role=Role.OWNER))
        await self.session.commit()
        return WorkspaceWithRole.of(workspace, Role.OWNER)

    async def list_for_user(self, user: User) -> list[WorkspaceWithRole]:
        return [
            WorkspaceWithRole.of(ws, role) for ws, role in await self.workspaces.list_for_user(user.id)
        ]

    async def convert_to_organization(self, owner: Membership, data: OrganizationConversion) -> WorkspaceWithRole:
        """Turn a personal workspace into an organisation, with its projects; its owner gets a
        new, empty personal workspace. Owners only (the route checks it)."""
        workspace = await self.session.get(Workspace, owner.workspace_id, with_for_update=True)
        assert workspace is not None  # the route found it
        if workspace.kind is not WorkspaceKind.PERSONAL:
            raise Conflict("This workspace is already an organisation")
        workspace.kind = WorkspaceKind.ORGANIZATION
        details: dict[str, object] = {}
        if data.name and data.name != workspace.name:
            details = {"from": workspace.name, "to": data.name}
            workspace.name = data.name
        await self._audit(owner, "workspace.converted_to_organization", **details)
        user = await UserRepository(self.session).get(owner.user_id)
        assert user is not None
        await self.create_personal(user)
        await self.session.commit()
        return WorkspaceWithRole.of(workspace, owner.role)

    async def update(self, member: Membership, data: WorkspaceUpdate) -> WorkspaceWithRole:
        workspace = member.workspace
        if data.name is not None and workspace.name != data.name:
            await self._audit(member, "workspace.renamed", **{"from": workspace.name, "to": data.name})
            workspace.name = data.name
        if data.member_permissions is not None:
            before = sorted(workspace.member_permissions or [])
            after = sorted(p.value for p in data.member_permissions)
            if before != after:
                await self._audit(member, "workspace.member_permissions_changed", **{"from": before, "to": after})
                workspace.member_permissions = after
        if data.unattended_paused is not None and data.unattended_paused != workspace.unattended_paused:
            if not data.unattended_paused and member.role is not Role.OWNER:
                raise Forbidden("Only owners can let agents act without approval again")
            await self._audit(member, "workspace.unattended_paused" if data.unattended_paused else "workspace.unattended_resumed")
            workspace.unattended_paused = data.unattended_paused
        if data.personal_keys is not None and data.personal_keys != workspace.personal_keys:
            await self._audit(member, "workspace.personal_keys_" + ("allowed" if data.personal_keys else "turned_off"))
            workspace.personal_keys = data.personal_keys
        await self.session.commit()
        return WorkspaceWithRole.of(workspace, member.role)

    async def list_members(self, workspace_id: uuid.UUID, viewer: Membership | None = None) -> list[MemberRead]:
        """Everyone in the workspace. With `viewer`, each person's projects are the ones they see
        among those the viewer sees, so a restricted project's name never leaks."""
        projects = await ProjectRepository(self.session).list(workspace_id, member=viewer)
        added: dict[uuid.UUID, set[uuid.UUID]] = {}
        for project_id, user_id in await self.session.execute(
            select(ProjectMember.project_id, ProjectMember.user_id).where(ProjectMember.workspace_id == workspace_id)
        ):
            added.setdefault(user_id, set()).add(project_id)

        def sees(m: Membership) -> list[uuid.UUID]:
            if m.role is Role.GUEST:
                return []
            if m.role in (Role.OWNER, Role.ADMIN):
                return [p.id for p in projects]
            mine = added.get(m.user_id, set())
            return [p.id for p in projects if p.access is ProjectAccessLevel.WORKSPACE or p.id in mine]

        return [
            MemberRead(
                user_id=user.id,
                email=user.email,
                display_name=user.display_name,
                title=user.title,
                avatar_updated_at=user.avatar_updated_at,
                role=m.role,
                joined_at=m.created_at,
                sees_all_projects=m.role in (Role.OWNER, Role.ADMIN),
                project_ids=sees(m),
            )
            for m, user in await self.members.list_with_users(workspace_id)
        ]

    async def avatar(self, member: Membership, user_id: uuid.UUID) -> UserAvatar:
        """A colleague's photo: they must be in the workspace too."""
        await self._get_member(member.workspace_id, user_id)
        return await ProfileService(self.session).avatar(user_id)

    async def change_role(
        self, actor: Membership, target_user_id: uuid.UUID, role: Role
    ) -> MemberRead:
        target = await self._get_member(actor.workspace_id, target_user_id)
        if actor.workspace.kind is WorkspaceKind.PERSONAL and role not in (Role.OWNER, Role.GUEST):
            raise Conflict("Personal workspaces have one owner plus read-only guests")
        touches_owner = role == Role.OWNER or target.role == Role.OWNER
        if touches_owner and actor.role != Role.OWNER:
            raise Forbidden("Only an owner can grant or change the owner role")
        if target.role == Role.OWNER and role != Role.OWNER:
            await self._ensure_other_owner(actor.workspace_id, target)
        if target.role != role:
            await self._audit(
                actor, "member.role_changed", target_user_id, **{"from": target.role.value, "to": role.value}
            )
        target.role = role
        await self.session.commit()
        members = await self.list_members(actor.workspace_id, actor)
        return next(m for m in members if m.user_id == target_user_id)

    async def transfer_ownership(self, actor: Membership, target_user_id: uuid.UUID) -> MemberRead:
        """Atomically make another member the owner and step the current owner down to admin."""
        if actor.role is not Role.OWNER:
            raise Forbidden("Only an owner can transfer ownership")
        if actor.workspace.kind is WorkspaceKind.PERSONAL:
            raise Conflict("A personal workspace can't be transferred")
        if target_user_id == actor.user_id:
            raise Conflict("You already own this workspace")
        target = await self._get_member(actor.workspace_id, target_user_id)
        if target.role is Role.GUEST:
            raise Conflict("Guests can't become owners; make them a member first")
        await self._audit(actor, "workspace.ownership_transferred", target_user_id)
        target.role = Role.OWNER
        actor.role = Role.ADMIN
        await self.session.commit()
        members = await self.list_members(actor.workspace_id, actor)
        return next(m for m in members if m.user_id == target_user_id)

    async def remove_member(self, actor: Membership, target_user_id: uuid.UUID) -> None:
        leaving = target_user_id == actor.user_id
        if not leaving and not can(actor, Permission.MANAGE_MEMBERS):
            raise Forbidden("You don't have permission to remove members")
        target = await self._get_member(actor.workspace_id, target_user_id)
        if target.role == Role.OWNER:
            if not leaving and actor.role != Role.OWNER:
                raise Forbidden("Only an owner can remove an owner")
            await self._ensure_other_owner(actor.workspace_id, target)
        await self._audit(
            actor, "member.left" if leaving else "member.removed", target_user_id, role=target.role.value
        )
        await self.members.delete(target)
        await self.session.commit()

    async def _get_member(self, workspace_id: uuid.UUID, user_id: uuid.UUID) -> Membership:
        member = await self.members.get(workspace_id, user_id, for_update=True)
        if member is None:
            raise NotFound("Member not found")
        return member

    async def _ensure_other_owner(self, workspace_id: uuid.UUID, target: Membership) -> None:
        owners = await self.members.lock_owners(workspace_id)
        if not any(o.id != target.id for o in owners):
            raise Conflict("A workspace must keep at least one owner")

