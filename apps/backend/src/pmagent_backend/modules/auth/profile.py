"""Your own profile: name, what you do, photo, and the ways you sign in."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core import security
from pmagent_backend.core.errors import Conflict, NotFound, Unprocessable

from .github import GitHubProfile
from .models import AuthSession, OAuthAccount, User, UserAvatar
from .repository import RefreshTokenRepository
from .schemas import LinkedAccount, PasswordChange, ProfileUpdate, SignInMethods, UserRead


class WrongPassword(Unprocessable):
    code = "wrong_password"

# The web app sends a 256 px square; this leaves room for other clients without storing photos.
MAX_AVATAR_BYTES = 512_000
AVATAR_TYPES = {"image/png", "image/jpeg", "image/webp"}
# The format's first bytes, so a file can't claim to be an image it isn't.
SIGNATURES = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/webp": (b"RIFF",),
}


class ProfileService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def update(self, user: User, data: ProfileUpdate) -> UserRead:
        if data.display_name is not None:
            user.display_name = data.display_name
        if data.title is not None:
            user.title = data.title or None
        await self.session.commit()
        return UserRead.model_validate(user)

    async def sign_in_methods(self, user: User) -> SignInMethods:
        accounts = await self.session.scalars(
            select(OAuthAccount).where(OAuthAccount.user_id == user.id).order_by(OAuthAccount.created_at)
        )
        return SignInMethods(
            password=user.password_hash is not None,
            email_link=True,
            accounts=[
                LinkedAccount(provider="github", login=a.login, linked_at=a.created_at)
                for a in accounts
                if a.provider == "github"
            ],
        )

    async def link_github(self, user: User, profile: GitHubProfile) -> SignInMethods:
        """Sign in with this GitHub account from now on (you're signed in, so its email doesn't
        need to match yours). 409 if it signs in to another account, or you've linked another."""
        linked = await self.session.scalar(
            select(OAuthAccount).where(OAuthAccount.provider == "github", OAuthAccount.provider_user_id == profile.id)
        )
        if linked is not None and linked.user_id != user.id:
            raise Conflict(f"GitHub account @{profile.login} already signs in to another dotrix account")
        if linked is None:
            mine = await self.session.scalar(
                select(OAuthAccount).where(OAuthAccount.user_id == user.id, OAuthAccount.provider == "github")
            )
            if mine is not None:
                raise Conflict(f"Unlink @{mine.login} first: an account links one GitHub account")
            self.session.add(OAuthAccount(
                user_id=user.id, provider="github", provider_user_id=profile.id, login=profile.login,
                created_at=datetime.now(UTC),
            ))
            try:
                await self.session.flush()
            except IntegrityError as exc:  # linked at the same moment elsewhere
                raise Conflict("That GitHub account was just linked; try again") from exc
        else:
            linked.login = profile.login
        await self.session.commit()
        return await self.sign_in_methods(user)

    async def change_password(self, user: User, data: PasswordChange, current_session: uuid.UUID | None) -> int:
        """A new password (or a first one). The current one must be right if you have one. Every
        other browser and app is signed out, in case someone else knew the old one; returns how many."""
        if user.password_hash is not None and not security.verify_password(
            user.password_hash, data.current_password or ""
        ):
            raise WrongPassword("Your current password isn't right")
        user.password_hash = security.hash_password(data.new_password)
        now = datetime.now(UTC)
        others = list(await self.session.scalars(
            select(AuthSession.id).where(
                AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None), AuthSession.id != current_session
            )
        ))
        tokens = RefreshTokenRepository(self.session)
        for session_id in others:
            await tokens.revoke_family(session_id, now)
        await self.session.commit()
        return len(others)

    async def unlink(self, user: User, provider: str) -> None:
        """Stop signing in with `provider`. Refused while it's your only way in besides email
        links, so a lost mailbox doesn't lock you out: set a password first."""
        accounts = list(
            await self.session.scalars(
                select(OAuthAccount).where(OAuthAccount.user_id == user.id, OAuthAccount.provider == provider)
            )
        )
        if not accounts:
            raise NotFound(f"No {provider} account is linked")
        others = await self.session.scalar(
            select(OAuthAccount.id).where(OAuthAccount.user_id == user.id, OAuthAccount.provider != provider)
        )
        if user.password_hash is None and others is None:
            raise Conflict("Set a password before unlinking: it's your only other way to sign in")
        for account in accounts:
            await self.session.delete(account)
        await self.session.commit()

    async def set_avatar(self, user: User, content_type: str, content: bytes) -> UserRead:
        if content_type not in AVATAR_TYPES:
            raise Unprocessable("A photo must be PNG, JPEG, or WebP")
        if len(content) > MAX_AVATAR_BYTES:
            raise Unprocessable("A photo can be at most 500 KB")
        if not content.startswith(SIGNATURES[content_type]):
            raise Unprocessable("That file isn't the image it says it is")
        avatar = await self.session.get(UserAvatar, user.id)
        if avatar is None:
            self.session.add(UserAvatar(user_id=user.id, content_type=content_type, content=content))
        else:
            avatar.content_type, avatar.content = content_type, content
        user.avatar_updated_at = datetime.now(UTC)
        await self.session.commit()
        return UserRead.model_validate(user)

    async def remove_avatar(self, user: User) -> UserRead:
        avatar = await self.session.get(UserAvatar, user.id)
        if avatar is not None:
            await self.session.delete(avatar)
        user.avatar_updated_at = None
        await self.session.commit()
        return UserRead.model_validate(user)

    async def avatar(self, user_id: uuid.UUID) -> UserAvatar:
        avatar = await self.session.get(UserAvatar, user_id)
        if avatar is None:
            raise NotFound("No photo")
        return avatar
