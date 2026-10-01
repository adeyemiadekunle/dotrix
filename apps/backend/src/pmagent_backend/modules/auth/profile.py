"""Your own profile: name, what you do, photo, and the ways you sign in."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core.errors import Conflict, NotFound, Unprocessable

from .models import OAuthAccount, User, UserAvatar
from .schemas import LinkedAccount, ProfileUpdate, SignInMethods, UserRead

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
