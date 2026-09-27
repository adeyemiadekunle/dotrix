from __future__ import annotations

import re
import secrets
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core.errors import Conflict, Forbidden, NotFound
from pmagent_backend.modules.auth.models import User

from .models import Membership, Role, Workspace, WorkspaceKind
from .permissions import Permission, has_permission
from .repository import MembershipRepository, WorkspaceRepository
from .schemas import MemberRead, WorkspaceCreate, WorkspaceUpdate, WorkspaceWithRole


def make_slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "workspace"
    return f"{base}-{secrets.token_hex(3)}"


class WorkspaceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.workspaces = WorkspaceRepository(session)
        self.members = MembershipRepository(session)

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
            WorkspaceWithRole.of(ws, role, via_org)
            for ws, role, via_org in await self.workspaces.list_for_user(user.id)
        ]

    async def update(self, member: Membership, data: WorkspaceUpdate) -> WorkspaceWithRole:
        workspace = member.workspace
        workspace.name = data.name
        await self.session.commit()
        return WorkspaceWithRole.of(workspace, member.role)

    async def list_members(self, workspace_id: uuid.UUID) -> list[MemberRead]:
        return [
            MemberRead(
                user_id=user.id,
                email=user.email,
                display_name=user.display_name,
                role=m.role,
                joined_at=m.created_at,
            )
            for m, user in await self.members.list_with_users(workspace_id)
        ]

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
        target.role = role
        await self.session.commit()
        members = await self.list_members(actor.workspace_id)
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
        target.role = Role.OWNER
        actor.role = Role.ADMIN
        await self.session.commit()
        members = await self.list_members(actor.workspace_id)
        return next(m for m in members if m.user_id == target_user_id)

    async def remove_member(self, actor: Membership, target_user_id: uuid.UUID) -> None:
        leaving = target_user_id == actor.user_id
        if not leaving and not has_permission(actor.role, Permission.MANAGE_MEMBERS):
            raise Forbidden("You don't have permission to remove members")
        target = await self._get_member(actor.workspace_id, target_user_id)
        if target.role == Role.OWNER:
            if not leaving and actor.role != Role.OWNER:
                raise Forbidden("Only an owner can remove an owner")
            await self._ensure_other_owner(actor.workspace_id, target)
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

