"""Admin console accounts, created and recovered from the server's command line.

These functions never commit: the caller owns the unit of work."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.email import EmailSender
from dotrix_backend.core.email_templates import PRODUCT, EmailContent, render
from dotrix_backend.core.errors import Conflict, Forbidden, InvalidLink, NotFound, Unprocessable
from dotrix_backend.core.security import generate_token, hash_password, hash_token, verify_password
from dotrix_backend.core.settings import Settings

from . import trail
from .models import AdminInvite, AdminRecoveryCode, AdminSession, AdminUser
from .schemas import AdminInviteAccept, AdminInviteCreate, AdminInviteRead, AdminListed, AdminUpdate
from .service import AdminService

MIN_PASSWORD_LENGTH = 12


async def create_admin(
    session: AsyncSession,
    *,
    email: str,
    name: str,
    password: str,
    role: str = "owner",
    actor_email: str | None = None,
    ip: str | None = None,
) -> AdminUser:
    """`actor_email` names who made it (`command line`); without it the new admin made itself (an invite)."""
    email = email.strip().lower()
    if len(password) < MIN_PASSWORD_LENGTH:
        raise Unprocessable(f"The password must be at least {MIN_PASSWORD_LENGTH} characters")
    if await session.scalar(select(AdminUser.id).where(AdminUser.email == email)) is not None:
        raise Conflict("An admin with this email already exists")
    now = datetime.now(UTC)
    admin = AdminUser(
        email=email, name=name, password_hash=hash_password(password), created_at=now, role=role, password_changed_at=now
    )
    session.add(admin)
    await session.flush()
    trail.record(
        session, "admin.created", admin=admin if actor_email is None else None,
        actor_email=actor_email, target_email=None if actor_email is None else email, ip=ip,
    )
    return admin


async def reset_admin_password(
    session: AsyncSession, *, email: str, password: str, actor_email: str | None = "command line"
) -> AdminUser:
    """Set a new password and sign the admin out everywhere."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise Unprocessable(f"The password must be at least {MIN_PASSWORD_LENGTH} characters")
    admin = await session.scalar(select(AdminUser).where(AdminUser.email == email.strip().lower()))
    if admin is None:
        raise NotFound("No admin with this email")
    admin.password_hash = hash_password(password)
    admin.password_changed_at = datetime.now(UTC)
    await session.execute(
        update(AdminSession)
        .where(AdminSession.admin_user_id == admin.id, AdminSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    trail.record(session, "admin.password_reset", actor_email=actor_email, target_email=admin.email)
    await session.flush()
    return admin


async def reset_admin_two_factor(
    session: AsyncSession, *, email: str, actor_email: str | None = "command line"
) -> AdminUser:
    """Clear an admin's second factor and sign them out everywhere: their next sign-in must set one up again."""
    admin = await session.scalar(select(AdminUser).where(AdminUser.email == email.strip().lower()))
    if admin is None:
        raise NotFound("No admin with this email")
    await clear_two_factor(session, admin)
    trail.record(session, "admin.two_factor_reset", actor_email=actor_email, target_email=admin.email)
    return admin


async def clear_two_factor(session: AsyncSession, admin: AdminUser) -> None:
    admin.totp_secret_encrypted = None
    admin.totp_enabled_at = None
    admin.totp_last_step = None
    await session.execute(delete(AdminRecoveryCode).where(AdminRecoveryCode.admin_user_id == admin.id))
    await session.execute(
        update(AdminSession)
        .where(AdminSession.admin_user_id == admin.id, AdminSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await session.flush()


async def list_admins(session: AsyncSession) -> list[AdminUser]:
    return list((await session.scalars(select(AdminUser).order_by(AdminUser.created_at))).all())


INVITE_TTL = timedelta(hours=72)


def _usable(invite: AdminInvite | None, now: datetime) -> AdminInvite:
    if invite is None or invite.accepted_at is not None or invite.revoked_at is not None or invite.expires_at <= now:
        raise InvalidLink()
    return invite


async def _revoke_sessions(session: AsyncSession, admin_id: object, *, keep: object | None = None) -> None:
    stmt = update(AdminSession).where(AdminSession.admin_user_id == admin_id, AdminSession.revoked_at.is_(None))
    if keep is not None:
        stmt = stmt.where(AdminSession.id != keep)
    await session.execute(stmt.values(revoked_at=datetime.now(UTC)))


class AdminAccounts:
    """Managing admins from the console: invites, roles, disabling, removing, own password."""

    def __init__(self, session: AsyncSession, settings: Settings, email: EmailSender) -> None:
        self.session = session
        self.settings = settings
        self.email = email

    async def _lock(self) -> None:
        # The same lock as the first sign-up, so "the last owner" checks and writes can't interleave.
        await self.session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended("admin:bootstrap", 0))))

    async def list(self) -> list[AdminListed]:
        last = (
            select(AdminSession.admin_user_id, func.max(AdminSession.created_at).label("at"))
            .group_by(AdminSession.admin_user_id)
            .subquery()
        )
        rows = await self.session.execute(
            select(AdminUser, last.c.at).outerjoin(last, last.c.admin_user_id == AdminUser.id).order_by(AdminUser.created_at)
        )
        return [
            AdminListed(
                id=a.id, email=a.email, name=a.name, role=a.role, created_at=a.created_at,
                disabled_at=a.disabled_at, last_sign_in_at=at, two_factor=a.totp_enabled_at is not None,
            )
            for a, at in rows.all()
        ]

    async def invite(self, owner: AdminUser, data: AdminInviteCreate, ip: str | None = None) -> AdminInviteRead:
        email = data.email.strip().lower()
        if await self.session.scalar(select(AdminUser.id).where(AdminUser.email == email)) is not None:
            raise Conflict("An admin with this email already exists")
        now = datetime.now(UTC)
        await self.session.execute(
            update(AdminInvite)
            .where(AdminInvite.email == email, AdminInvite.accepted_at.is_(None), AdminInvite.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        token = generate_token()
        invite = AdminInvite(
            email=email, role=data.role, token_hash=hash_token(token), invited_by_id=owner.id,
            created_at=now, expires_at=now + INVITE_TTL,
        )
        self.session.add(invite)
        trail.record(self.session, "admin.invited", admin=owner, target_email=email, ip=ip)
        await self.session.commit()
        path = f"/#/accept?token={token}"
        read = self._read(invite, owner.email)
        base = self.settings.admin_url
        if base:
            await self.email.send(
                render(email, EmailContent(
                    subject=f"{owner.name} invited you to the {PRODUCT} admin console",
                    heading=f"Join the {PRODUCT} admin console",
                    paragraphs=[f"{owner.name} invited you to be an admin ({data.role})."],
                    action_label="Accept the invite",
                    action_url=f"{base.rstrip('/')}{path}",
                    note=f"This invite expires in 72 hours, works once and only for {email}.",
                ))
            )
            read.emailed = True
        else:
            read.link_path = path
            read.note = "DOTRIX_ADMIN_URL is not set, so no email was sent. Pass this link on yourself."
        return read

    def _read(self, invite: AdminInvite, invited_by: str | None) -> AdminInviteRead:
        return AdminInviteRead(
            id=invite.id, email=invite.email, role=invite.role, created_at=invite.created_at,
            expires_at=invite.expires_at, invited_by=invited_by,
        )

    async def pending_invites(self) -> list[AdminInviteRead]:
        now = datetime.now(UTC)
        rows = await self.session.execute(
            select(AdminInvite, AdminUser.email)
            .outerjoin(AdminUser, AdminUser.id == AdminInvite.invited_by_id)
            .where(AdminInvite.accepted_at.is_(None), AdminInvite.revoked_at.is_(None), AdminInvite.expires_at > now)
            .order_by(AdminInvite.created_at.desc())
        )
        return [self._read(invite, by) for invite, by in rows.all()]

    async def revoke_invite(self, owner: AdminUser, invite_id: object, ip: str | None = None) -> None:
        invite = await self.session.get(AdminInvite, invite_id, with_for_update=True)
        if invite is None or invite.accepted_at is not None:
            raise NotFound("Invite not found")
        if invite.revoked_at is None:
            invite.revoked_at = datetime.now(UTC)
            trail.record(self.session, "admin.invite_revoked", admin=owner, target_email=invite.email, ip=ip)
        await self.session.commit()

    async def preview(self, token: str) -> AdminInvite:
        invite = await self.session.scalar(select(AdminInvite).where(AdminInvite.token_hash == hash_token(token)))
        return _usable(invite, datetime.now(UTC))

    async def accept(self, data: AdminInviteAccept, ip: str | None = None) -> tuple[str, str]:
        """Use the invite up and sign the new admin in. The invite row is locked, so one token
        creates one account."""
        invite = await self.session.scalar(
            select(AdminInvite).where(AdminInvite.token_hash == hash_token(data.token)).with_for_update()
        )
        now = datetime.now(UTC)
        invite = _usable(invite, now)
        admin = await create_admin(
            self.session, email=invite.email, name=data.name, password=data.password, role=invite.role, ip=ip
        )
        invite.accepted_at = now
        pair = await AdminService(self.session, self.settings)._tokens(admin)
        await self.session.commit()
        return pair

    async def _other_active_owners(self, admin: AdminUser) -> int:
        return (
            await self.session.scalar(
                select(func.count(AdminUser.id)).where(
                    AdminUser.role == "owner", AdminUser.disabled_at.is_(None), AdminUser.id != admin.id
                )
            )
            or 0
        )

    async def update(self, owner: AdminUser, admin_id: object, data: AdminUpdate, ip: str | None = None) -> AdminListed:
        await self._lock()
        admin = await self.session.get(AdminUser, admin_id, with_for_update=True)
        if admin is None:
            raise NotFound("Admin not found")
        was_active_owner = admin.role == "owner" and admin.disabled_at is None
        role = data.role or admin.role
        disabled = admin.disabled_at is not None if data.disabled is None else data.disabled
        if was_active_owner and (role != "owner" or disabled) and await self._other_active_owners(admin) == 0:
            raise Conflict("There must be at least one owner")
        if role != admin.role:
            trail.record(self.session, "admin.role_changed", admin=owner, target_email=admin.email, ip=ip)
        admin.role = role
        if disabled and admin.disabled_at is None:
            admin.disabled_at = datetime.now(UTC)
            await _revoke_sessions(self.session, admin.id)
            trail.record(self.session, "admin.disabled", admin=owner, target_email=admin.email, ip=ip)
        elif not disabled:
            if admin.disabled_at is not None:
                trail.record(self.session, "admin.enabled", admin=owner, target_email=admin.email, ip=ip)
            admin.disabled_at = None
        await self.session.commit()
        return next(a for a in await self.list() if a.id == admin.id)

    async def remove(self, owner: AdminUser, admin_id: object, ip: str | None = None) -> None:
        await self._lock()
        admin = await self.session.get(AdminUser, admin_id, with_for_update=True)
        if admin is None:
            raise NotFound("Admin not found")
        if admin.role == "owner" and admin.disabled_at is None and await self._other_active_owners(admin) == 0:
            raise Conflict("There must be at least one owner")
        trail.record(self.session, "admin.removed", admin=owner, target_email=admin.email, ip=ip)
        await self.session.delete(admin)  # sessions cascade
        await self.session.commit()

    async def reset_two_factor(self, owner: AdminUser, admin_id: object, ip: str | None = None) -> None:
        """An owner clears another admin's second factor (a lost device). Not your own: that is the
        command line's job, so one stolen owner session can't strip its own protection."""
        admin = await self.session.get(AdminUser, admin_id, with_for_update=True)
        if admin is None:
            raise NotFound("Admin not found")
        if admin.id == owner.id:
            raise Conflict("You can't reset your own second factor here")
        await clear_two_factor(self.session, admin)
        trail.record(self.session, "admin.two_factor_reset", admin=owner, target_email=admin.email, ip=ip)
        await self.session.commit()

    async def change_password(
        self, admin: AdminUser, current: str, new: str, session_id: object, ip: str | None = None
    ) -> None:
        if not verify_password(admin.password_hash, current):
            raise Forbidden("The current password is wrong")
        admin.password_hash = hash_password(new)
        admin.password_changed_at = datetime.now(UTC)
        await _revoke_sessions(self.session, admin.id, keep=session_id)
        trail.record(self.session, "admin.password_changed", admin=admin, ip=ip)
        await self.session.commit()

    async def revoke_other_sessions(self, admin: AdminUser, session_id: object, ip: str | None = None) -> None:
        await _revoke_sessions(self.session, admin.id, keep=session_id)
        trail.record(self.session, "admin.sessions_revoked", admin=admin, ip=ip)
        await self.session.commit()
