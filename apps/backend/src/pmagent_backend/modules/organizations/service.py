"""Organisations: their people and the workspaces they own. Nothing here reads or grants
access to workspace content; that stays with workspace membership."""
from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core.errors import Conflict, Forbidden, NotFound
from pmagent_backend.modules.audit.service import AuditLog
from pmagent_backend.modules.auth.models import User
from pmagent_backend.modules.knowledge.models import AuthorType
from pmagent_backend.modules.projects.models import Project
from pmagent_backend.modules.workspaces.models import Membership, Role, Workspace, WorkspaceKind
from pmagent_backend.modules.workspaces.schemas import MemberRead
from pmagent_backend.modules.workspaces.service import WorkspaceService, make_slug

from .models import Organization, OrgMembership, OrgRole
from .permissions import OrgPermission, has_org_permission
from .schemas import (
    OrgCreate,
    OrgMemberAdd,
    OrgMemberRead,
    OrgUpdate,
    OrgWithRole,
    OrgWorkspaceCreate,
    OrgWorkspaceRead,
)


async def ensure_org_member(session: AsyncSession, workspace: Workspace, user_id: uuid.UUID) -> None:
    """Everyone in an organisation's workspace belongs to the organisation. Call whenever a
    person joins an org workspace (invites, placements, attaching a workspace)."""
    if workspace.organization_id is None:
        return
    exists = await session.scalar(
        select(OrgMembership.id).where(
            OrgMembership.organization_id == workspace.organization_id, OrgMembership.user_id == user_id
        )
    )
    if exists is None:
        session.add(OrgMembership(organization_id=workspace.organization_id, user_id=user_id, role=OrgRole.MEMBER))


class OrganizationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- the organisation --------------------------------------------------------------

    async def create(self, user: User, data: OrgCreate) -> OrgWithRole:
        org = Organization(name=data.name, slug=make_slug(data.name), created_by_id=user.id)
        self.session.add(org)
        await self.session.flush()
        self.session.add(OrgMembership(organization_id=org.id, user_id=user.id, role=OrgRole.OWNER))
        await self.session.commit()
        return OrgWithRole(**_org(org), role=OrgRole.OWNER)

    async def list_for_user(self, user: User) -> list[OrgWithRole]:
        rows = await self.session.execute(
            select(Organization, OrgMembership.role)
            .join(OrgMembership, OrgMembership.organization_id == Organization.id)
            .where(OrgMembership.user_id == user.id)
            .order_by(Organization.name)
        )
        return [OrgWithRole(**_org(org), role=role) for org, role in rows]

    async def membership(self, org_id: uuid.UUID, user_id: uuid.UUID, *, for_update: bool = False) -> OrgMembership | None:
        stmt = select(OrgMembership).where(OrgMembership.organization_id == org_id, OrgMembership.user_id == user_id)
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def update(self, actor: OrgMembership, data: OrgUpdate) -> OrgWithRole:
        org = await self._org(actor.organization_id)
        org.name = data.name
        await self.session.commit()
        await self.session.refresh(org)
        return OrgWithRole(**_org(org), role=actor.role)

    async def get(self, actor: OrgMembership) -> OrgWithRole:
        return OrgWithRole(**_org(await self._org(actor.organization_id)), role=actor.role)

    # -- people --------------------------------------------------------------------------

    async def members(self, org_id: uuid.UUID) -> list[OrgMemberRead]:
        rows = await self.session.execute(
            select(OrgMembership, User)
            .join(User, User.id == OrgMembership.user_id)
            .where(OrgMembership.organization_id == org_id)
            .order_by(OrgMembership.created_at)
        )
        return [
            OrgMemberRead(user_id=u.id, email=u.email, display_name=u.display_name, role=m.role, joined_at=m.created_at)
            for m, u in rows
        ]

    async def add_member(self, actor: OrgMembership, data: OrgMemberAdd) -> OrgMemberRead:
        if data.role is OrgRole.OWNER and actor.role is not OrgRole.OWNER:
            raise Forbidden("Only an owner can add owners")
        user = await self.session.scalar(select(User).where(User.email == data.email))
        if user is None:
            raise NotFound("No account with that email yet; ask them to sign up, then add them")
        if await self.membership(actor.organization_id, user.id):
            raise Conflict("They're already in this organisation")
        self.session.add(OrgMembership(organization_id=actor.organization_id, user_id=user.id, role=data.role))
        await self.session.commit()
        return await self._member(actor.organization_id, user.id)

    async def change_role(self, actor: OrgMembership, user_id: uuid.UUID, role: OrgRole) -> OrgMemberRead:
        target = await self._require_member(actor.organization_id, user_id, for_update=True)
        if (role is OrgRole.OWNER or target.role is OrgRole.OWNER) and actor.role is not OrgRole.OWNER:
            raise Forbidden("Only an owner can grant or change the owner role")
        if target.role is OrgRole.OWNER and role is not OrgRole.OWNER:
            await self._keep_an_owner(actor.organization_id, target)
        target.role = role
        await self.session.commit()
        return await self._member(actor.organization_id, user_id)

    async def remove_member(self, actor: OrgMembership, user_id: uuid.UUID) -> None:
        """Leaving (or being removed from) an organisation also removes you from its workspaces."""
        leaving = user_id == actor.user_id
        if not leaving and not has_org_permission(actor.role, OrgPermission.MANAGE_PEOPLE):
            raise Forbidden("You can't remove people from this organisation")
        target = await self._require_member(actor.organization_id, user_id, for_update=True)
        if target.role is OrgRole.OWNER:
            if not leaving and actor.role is not OrgRole.OWNER:
                raise Forbidden("Only an owner can remove an owner")
            await self._keep_an_owner(actor.organization_id, target)
        org_workspaces = select(Workspace.id).where(Workspace.organization_id == actor.organization_id)
        owned = list(
            await self.session.scalars(
                select(Workspace.name)
                .join(Membership, Membership.workspace_id == Workspace.id)
                .where(Workspace.id.in_(org_workspaces), Membership.user_id == user_id, Membership.role == Role.OWNER)
            )
        )
        if owned:
            raise Conflict(f"They own {', '.join(owned)}; transfer ownership of those workspaces first")
        await self.session.execute(
            delete(Membership).where(Membership.workspace_id.in_(org_workspaces), Membership.user_id == user_id)
        )
        await self.session.delete(target)
        await self.session.commit()

    # -- workspaces ------------------------------------------------------------------------

    async def workspaces(self, actor: OrgMembership) -> list[OrgWorkspaceRead]:
        """Admins see every workspace in the organisation (names and sizes); members see theirs."""
        members = (
            select(Membership.workspace_id, func.count().label("n")).group_by(Membership.workspace_id).subquery()
        )
        projects = select(Project.workspace_id, func.count().label("n")).group_by(Project.workspace_id).subquery()
        mine = select(Membership.workspace_id, Membership.role).where(Membership.user_id == actor.user_id).subquery()
        stmt = (
            select(Workspace, func.coalesce(members.c.n, 0), func.coalesce(projects.c.n, 0), mine.c.role)
            .outerjoin(members, members.c.workspace_id == Workspace.id)
            .outerjoin(projects, projects.c.workspace_id == Workspace.id)
            .outerjoin(mine, mine.c.workspace_id == Workspace.id)
            .where(Workspace.organization_id == actor.organization_id)
            .order_by(Workspace.name)
        )
        if not has_org_permission(actor.role, OrgPermission.MANAGE_WORKSPACES):
            stmt = stmt.where(mine.c.role.is_not(None))
        return [
            OrgWorkspaceRead(
                id=ws.id, name=ws.name, slug=ws.slug, kind=ws.kind, created_at=ws.created_at,
                members=n_members, projects=n_projects,
                # Org owners see every workspace; admins and members only their own.
                your_role=role or (Role.OWNER if actor.role is OrgRole.OWNER else None),
                via_organization=role is None and actor.role is OrgRole.OWNER,
            )
            for ws, n_members, n_projects, role in await self.session.execute(stmt)
        ]

    async def create_workspace(self, actor: OrgMembership, data: OrgWorkspaceCreate) -> OrgWorkspaceRead:
        owner_id = data.owner_user_id or actor.user_id
        await self._require_member(actor.organization_id, owner_id)
        workspace = Workspace(
            name=data.name, slug=make_slug(data.name), kind=data.kind,
            created_by_id=actor.user_id, organization_id=actor.organization_id,
        )
        self.session.add(workspace)
        await self.session.flush()
        self.session.add(Membership(workspace_id=workspace.id, user_id=owner_id, role=Role.OWNER))
        await self.session.commit()
        return await self._org_workspace(actor, workspace.id)

    async def attach(self, actor: OrgMembership, workspace_id: uuid.UUID) -> OrgWorkspaceRead:
        """Bring a workspace you own into the organisation; its people join the organisation. A
        personal workspace becomes a team workspace, and its owner gets a new personal one."""
        workspace = await self.session.get(Workspace, workspace_id, with_for_update=True)
        own = workspace and await self.session.scalar(
            select(Membership.role).where(Membership.workspace_id == workspace_id, Membership.user_id == actor.user_id)
        )
        if workspace is None or own is None:
            raise NotFound("Workspace not found")
        if own is not Role.OWNER:
            raise Forbidden("Only the workspace's owner can bring it into an organisation")
        if workspace.organization_id is not None:
            raise Conflict("That workspace already belongs to an organisation")
        if workspace.kind is WorkspaceKind.PERSONAL:
            # It becomes a team workspace, with its projects; you get a new, empty personal one.
            workspace.kind = WorkspaceKind.TEAM
            owner = await self.session.get(User, actor.user_id)
            await WorkspaceService(self.session).create_personal(owner)
        workspace.organization_id = actor.organization_id
        AuditLog(self.session).record(
            workspace_id=workspace_id, action="workspace.added_to_organization", target=workspace.name,
            actor_type=AuthorType.USER, actor_user_id=actor.user_id,
            details={"organization_id": str(actor.organization_id)},
        )
        for user_id in await self.session.scalars(select(Membership.user_id).where(Membership.workspace_id == workspace_id)):
            await ensure_org_member(self.session, workspace, user_id)
        await self.session.commit()
        return await self._org_workspace(actor, workspace_id)

    async def detach(self, actor: OrgMembership, workspace_id: uuid.UUID) -> None:
        workspace = await self._org_ws(actor, workspace_id)
        workspace.organization_id = None  # its people stay org members; remove them separately if needed
        AuditLog(self.session).record(
            workspace_id=workspace_id, action="workspace.removed_from_organization", target=workspace.name,
            actor_type=AuthorType.USER, actor_user_id=actor.user_id,
            details={"organization_id": str(actor.organization_id)},
        )
        await self.session.commit()

    async def workspace_members(self, actor: OrgMembership, workspace_id: uuid.UUID) -> list[MemberRead]:
        await self._org_ws(actor, workspace_id)
        rows = await self.session.execute(
            select(Membership, User).join(User, User.id == Membership.user_id)
            .where(Membership.workspace_id == workspace_id).order_by(Membership.created_at)
        )
        return [
            MemberRead(user_id=u.id, email=u.email, display_name=u.display_name, role=m.role, joined_at=m.created_at)
            for m, u in rows
        ]

    async def place(self, actor: OrgMembership, workspace_id: uuid.UUID, user_id: uuid.UUID, role: Role) -> list[MemberRead]:
        """Put an org member into one of the organisation's workspaces, or change their role there.
        Org admins can't place themselves: seeing a workspace's work needs its owner's say (org
        owners already see every workspace)."""
        if user_id == actor.user_id and actor.role is not OrgRole.OWNER:
            raise Forbidden("Org admins can't add themselves to a workspace; ask its owner to add you")
        await self._org_ws(actor, workspace_id)
        await self._require_member(actor.organization_id, user_id)
        existing = await self.session.scalar(
            select(Membership).where(Membership.workspace_id == workspace_id, Membership.user_id == user_id).with_for_update()
        )
        if existing is None:
            self.session.add(Membership(workspace_id=workspace_id, user_id=user_id, role=role))
            await self._audit_placement(actor, workspace_id, user_id, "member.placed", role=role.value)
        elif existing.role is Role.OWNER:
            raise Conflict("That's the workspace's owner; ownership changes happen in the workspace")
        else:
            if existing.role is not role:
                await self._audit_placement(
                    actor, workspace_id, user_id, "member.role_changed", **{"from": existing.role.value, "to": role.value}
                )
            existing.role = role
        await self.session.commit()
        return await self.workspace_members(actor, workspace_id)

    async def unplace(self, actor: OrgMembership, workspace_id: uuid.UUID, user_id: uuid.UUID) -> None:
        await self._org_ws(actor, workspace_id)
        existing = await self.session.scalar(
            select(Membership).where(Membership.workspace_id == workspace_id, Membership.user_id == user_id)
        )
        if existing is None:
            raise NotFound("They aren't in that workspace")
        if existing.role is Role.OWNER:
            raise Conflict("That's the workspace's owner; transfer ownership in the workspace first")
        await self._audit_placement(actor, workspace_id, user_id, "member.removed", role=existing.role.value)
        await self.session.delete(existing)
        await self.session.commit()

    # -- helpers ---------------------------------------------------------------------------

    async def _audit_placement(
        self, actor: OrgMembership, workspace_id: uuid.UUID, user_id: uuid.UUID, action: str, **details: object
    ) -> None:
        """People changes made by the organisation land in the workspace's own audit log."""
        user = await self.session.get(User, user_id)
        AuditLog(self.session).record(
            workspace_id=workspace_id,
            action=action,
            target=user.email if user else str(user_id),
            actor_type=AuthorType.USER,
            actor_user_id=actor.user_id,
            details={**details, "user_id": str(user_id), "by_organization": str(actor.organization_id)},
        )

    async def _org(self, org_id: uuid.UUID) -> Organization:
        org = await self.session.get(Organization, org_id)
        if org is None:
            raise NotFound("Organisation not found")
        return org

    async def _org_ws(self, actor: OrgMembership, workspace_id: uuid.UUID) -> Workspace:
        workspace = await self.session.get(Workspace, workspace_id)
        if workspace is None or workspace.organization_id != actor.organization_id:
            raise NotFound("No such workspace in this organisation")
        return workspace

    async def _org_workspace(self, actor: OrgMembership, workspace_id: uuid.UUID) -> OrgWorkspaceRead:
        return next(w for w in await self.workspaces(actor) if w.id == workspace_id)

    async def _require_member(self, org_id: uuid.UUID, user_id: uuid.UUID, *, for_update: bool = False) -> OrgMembership:
        member = await self.membership(org_id, user_id, for_update=for_update)
        if member is None:
            raise NotFound("That person isn't in this organisation")
        return member

    async def _member(self, org_id: uuid.UUID, user_id: uuid.UUID) -> OrgMemberRead:
        return next(m for m in await self.members(org_id) if m.user_id == user_id)

    async def _keep_an_owner(self, org_id: uuid.UUID, target: OrgMembership) -> None:
        owners = list(
            await self.session.scalars(
                select(OrgMembership).where(OrgMembership.organization_id == org_id, OrgMembership.role == OrgRole.OWNER)
                .with_for_update()
            )
        )
        if not any(o.id != target.id for o in owners):
            raise Conflict("An organisation must keep at least one owner")


def _org(org: Organization) -> dict:
    return {"id": org.id, "name": org.name, "slug": org.slug, "created_at": org.created_at}
