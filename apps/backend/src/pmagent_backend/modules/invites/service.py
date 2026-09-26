"""Invites by email and by shareable link (FR-4).

Tokens are shown once (in the email, or in the create-link response) and
stored only as SHA-256 hashes. Tokens travel in request bodies, never URL
paths, so they don't end up in access logs.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core import security
from pmagent_backend.core.email import EmailMessage, EmailSender
from pmagent_backend.core.errors import Conflict, Forbidden, InvalidLink, NotFound
from pmagent_backend.core.settings import Settings
from pmagent_backend.modules.auth.models import User
from pmagent_backend.modules.auth.repository import UserRepository
from pmagent_backend.modules.workspaces.models import Membership, Role, WorkspaceKind
from pmagent_backend.modules.workspaces.repository import MembershipRepository
from pmagent_backend.modules.workspaces.schemas import WorkspaceWithRole

from .models import Invite, InviteKind
from .repository import InviteRepository
from .schemas import (
    EmailInviteCreate,
    InvitePreview,
    InviteRead,
    LinkInviteCreate,
    LinkInviteCreated,
)

EMAIL_INVITE_TTL = timedelta(days=7)


def _now() -> datetime:
    return datetime.now(UTC)


class InviteService:
    def __init__(self, session: AsyncSession, settings: Settings, email: EmailSender) -> None:
        self.session = session
        self.settings = settings
        self.email = email
        self.invites = InviteRepository(session)
        self.members = MembershipRepository(session)
        self.users = UserRepository(session)

    async def invite_by_email(
        self, actor: Membership, inviter: User, data: EmailInviteCreate
    ) -> InviteRead:
        self._check_role_allowed(actor, data.role)
        existing = await self.users.get_by_email(data.email)
        if existing and await self.members.get(actor.workspace_id, existing.id):
            raise Conflict("That person is already a member of this workspace")

        now = _now()
        await self.invites.revoke_pending_for_email(actor.workspace_id, data.email, now)
        token = security.generate_token()
        invite = Invite(
            workspace_id=actor.workspace_id,
            kind=InviteKind.EMAIL,
            email=data.email,
            role=data.role,
            token_hash=security.hash_token(token),
            invited_by_id=inviter.id,
            created_at=now,
            expires_at=now + EMAIL_INVITE_TTL,
        )
        self.invites.add(invite)
        await self.session.commit()

        workspace = actor.workspace.name
        await self.email.send(
            EmailMessage(
                to=data.email,
                subject=f"{inviter.display_name} invited you to {workspace} on pmagent",
                body=(
                    f"{inviter.display_name} invited you to join {workspace} as {data.role}.\n\n"
                    f"Accept the invite: {self._accept_url(token)}\n\n"
                    f"This invite expires in {EMAIL_INVITE_TTL.days} days."
                ),
            )
        )
        return InviteRead.model_validate(invite)

    async def create_link(
        self, actor: Membership, inviter: User, data: LinkInviteCreate
    ) -> LinkInviteCreated:
        self._check_role_allowed(actor, data.role)
        now = _now()
        token = security.generate_token()
        invite = Invite(
            workspace_id=actor.workspace_id,
            kind=InviteKind.LINK,
            role=data.role,
            token_hash=security.hash_token(token),
            invited_by_id=inviter.id,
            created_at=now,
            expires_at=now + timedelta(days=data.expires_in_days),
            max_uses=data.max_uses,
        )
        self.invites.add(invite)
        await self.session.commit()
        return LinkInviteCreated(
            **InviteRead.model_validate(invite).model_dump(), url=self._accept_url(token)
        )

    async def list_active(self, workspace_id: uuid.UUID) -> list[InviteRead]:
        return [
            InviteRead.model_validate(i) for i in await self.invites.list_active(workspace_id, _now())
        ]

    async def revoke(self, workspace_id: uuid.UUID, invite_id: uuid.UUID) -> None:
        invite = await self.invites.get(workspace_id, invite_id)
        if invite is None:
            raise NotFound("Invite not found")
        invite.revoked_at = invite.revoked_at or _now()
        await self.session.commit()

    async def preview(self, token: str) -> InvitePreview:
        invite = await self._usable(token)
        inviter = await self.users.get(invite.invited_by_id) if invite.invited_by_id else None
        return InvitePreview(
            workspace_name=invite.workspace.name,
            workspace_kind=invite.workspace.kind,
            role=invite.role,
            invited_by=inviter.display_name if inviter else None,
            email=invite.email,
            expires_at=invite.expires_at,
        )

    async def accept(self, user: User, token: str) -> WorkspaceWithRole:
        now = _now()
        invite = await self._usable(token, for_update=True)
        if invite.kind is InviteKind.EMAIL:
            if invite.email != user.email:
                raise Forbidden(
                    "This invite was sent to a different email address. "
                    "Sign in with that address to accept it."
                )
            invite.accepted_at = now
            # The token arrived in that inbox, which proves the address.
            user.email_verified_at = user.email_verified_at or now

        membership = await self.members.get(invite.workspace_id, user.id)
        if membership is None:
            membership = Membership(workspace_id=invite.workspace_id, user_id=user.id, role=invite.role)
            self.members.add(membership)
            if invite.kind is InviteKind.LINK:
                invite.use_count += 1
        # Already a member: keep the current role; an invite never changes it.
        await self.session.commit()
        return WorkspaceWithRole.of(invite.workspace, membership.role)

    # -- helpers -----------------------------------------------------------------

    def _check_role_allowed(self, actor: Membership, role: Role) -> None:
        if actor.workspace.kind is WorkspaceKind.PERSONAL and role is not Role.GUEST:
            raise Conflict("Personal workspaces can only invite read-only guests")
        if role is Role.ADMIN and actor.role not in (Role.OWNER, Role.ADMIN):
            raise Forbidden("Only owners and admins can invite admins")

    async def _usable(self, token: str, *, for_update: bool = False) -> Invite:
        invite = await self.invites.get_by_hash(security.hash_token(token), for_update=for_update)
        if invite is None or not invite.is_usable(_now()):
            raise InvalidLink()
        return invite

    def _accept_url(self, token: str) -> str:
        return f"{self.settings.app_url.rstrip('/')}/invites/accept?{urlencode({'token': token})}"
