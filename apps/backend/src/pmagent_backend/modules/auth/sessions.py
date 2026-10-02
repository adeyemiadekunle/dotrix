"""Where you're signed in: browsers and the desktop app, one session per refresh-token family."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core.errors import NotFound
from pmagent_backend.core.settings import Settings

from .models import AuthSession, SessionClient, User
from .repository import RefreshTokenRepository
from .schemas import SessionRead


@dataclass(frozen=True)
class ClientInfo:
    """Who's signing in: the browser's or app's User-Agent and address (as the API sees them)."""

    user_agent: str
    ip: str | None


_BROWSERS = [  # order matters: Edge and Opera say "Chrome" too, and Chrome says "Safari"
    ("Edg/", "Edge"),
    ("OPR/", "Opera"),
    ("Firefox/", "Firefox"),
    ("Chrome/", "Chrome"),
    ("Safari/", "Safari"),
]
_SYSTEMS = [
    (r"iPhone|iPad", "iOS"),
    (r"Android", "Android"),
    (r"Windows", "Windows"),
    (r"Mac OS X|Macintosh", "macOS"),
    (r"CrOS", "ChromeOS"),
    (r"Linux", "Linux"),
]


def describe(user_agent: str) -> tuple[SessionClient, str]:
    """What signed in, for people to recognise: ("desktop", "Desktop app on macOS"),
    ("web", "Firefox on Windows"). Only for display; never trusted for anything."""
    system = next((name for pattern, name in _SYSTEMS if re.search(pattern, user_agent)), None)
    on = f" on {system}" if system else ""
    if "Electron/" in user_agent:
        return SessionClient.DESKTOP, f"Desktop app{on}"
    browser = next((name for marker, name in _BROWSERS if marker in user_agent), None)
    if browser:
        return SessionClient.WEB, f"{browser}{on}"
    return SessionClient.OTHER, f"Unknown app{on}" if system else "Unknown app"


def _now() -> datetime:
    return datetime.now(UTC)


class SessionService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _active(self, now: datetime) -> list:
        # A session lasts as long as its refresh token: each refresh renews it.
        idle_limit = now - timedelta(days=self.settings.refresh_token_ttl_days)
        return [AuthSession.revoked_at.is_(None), AuthSession.last_used_at > idle_limit]

    async def list(self, user: User, current: uuid.UUID | None) -> list[SessionRead]:
        """Your signed-in browsers and apps, the one you're using first, then the latest used."""
        rows = await self.session.scalars(
            select(AuthSession)
            .where(AuthSession.user_id == user.id, *self._active(_now()))
            .order_by(AuthSession.last_used_at.desc())
        )
        sessions = [
            SessionRead(
                id=s.id, client=s.client, device=s.device, ip=s.ip, created_at=s.created_at,
                last_used_at=s.last_used_at, current=s.id == current,
            )
            for s in rows
        ]
        return sorted(sessions, key=lambda s: not s.current)

    async def sign_out(self, user: User, session_id: uuid.UUID) -> None:
        """Sign one of your sessions out (yours only: someone else's is a 404)."""
        found = await self.session.scalar(
            select(AuthSession.id).where(AuthSession.id == session_id, AuthSession.user_id == user.id, *self._active(_now()))
        )
        if found is None:
            raise NotFound("No such session")
        await RefreshTokenRepository(self.session).revoke_family(session_id, _now())
        await self.session.commit()

    async def sign_out_others(self, user: User, current: uuid.UUID | None) -> int:
        """Every session but the one you're using. Returns how many were signed out."""
        now = _now()
        ids = list(await self.session.scalars(
            select(AuthSession.id).where(AuthSession.user_id == user.id, AuthSession.id != current, *self._active(now))
        ))
        tokens = RefreshTokenRepository(self.session)
        for session_id in ids:
            await tokens.revoke_family(session_id, now)
        await self.session.commit()
        return len(ids)
