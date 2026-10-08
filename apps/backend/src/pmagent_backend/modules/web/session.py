"""The browser's session cookies, and one refresh shared by requests that need it at once.

The page never sees a token: the access and refresh tokens are httpOnly cookies. `pm_access`
goes with every request (`Path=/`); `pm_refresh` only to `/api/auth`, where it's used. A third,
readable cookie (`pm_session`, no secret in it) only tells the page someone is signed in, so it
can send people to the sign-in page without a round trip; the API is what checks.

Cookie-authenticated requests that change something must carry `X-Requested-With`: a page on
another site can't add that header without CORS allowing it, so a forged form or link is
refused (CSRF). API tokens and bearer access tokens don't need it.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from pmagent_backend.core import security
from pmagent_backend.core.errors import Forbidden
from pmagent_backend.core.settings import Settings
from pmagent_backend.modules.auth.schemas import TokenPair

ACCESS_COOKIE = "pm_access"
REFRESH_COOKIE = "pm_refresh"
SIGNED_IN_COOKIE = "pm_session"
REFRESH_PATH = "/api/auth"
WEB_HEADER = "x-requested-with"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _secure(settings: Settings) -> bool:
    return settings.env == "production"


def set_session(response: Response, tokens: TokenPair, settings: Settings) -> None:
    refresh_max_age = settings.refresh_token_ttl_days * 24 * 3600
    secure = _secure(settings)
    response.set_cookie(
        ACCESS_COOKIE, tokens.access_token, max_age=tokens.expires_in, path="/",
        httponly=True, secure=secure, samesite="lax",
    )
    response.set_cookie(
        REFRESH_COOKIE, tokens.refresh_token, max_age=refresh_max_age, path=REFRESH_PATH,
        httponly=True, secure=secure, samesite="lax",
    )
    response.set_cookie(SIGNED_IN_COOKIE, "1", max_age=refresh_max_age, path="/", secure=secure, samesite="lax")
    # The Next.js web app kept the refresh token at `Path=/`; two of the same name would be ambiguous.
    response.delete_cookie(REFRESH_COOKIE, path="/")


def clear_session(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH)
    response.delete_cookie(REFRESH_COOKIE, path="/")
    response.delete_cookie(SIGNED_IN_COOKIE, path="/")


def require_web_header(request: Request) -> None:
    """Refuse a cookie-authenticated change that a page on another site could have sent."""
    if request.method not in SAFE_METHODS and not request.headers.get(WEB_HEADER):
        raise Forbidden("Requests from the web app need the X-Requested-With header")


class SharedRefresh:
    """One refresh per refresh token, remembered briefly.

    The API rotates refresh tokens and treats a reused one as theft (it signs the session out). A
    page fires several requests at once, so when the access token expires several would refresh
    with the same token; requests already in flight with the old cookie get the same new pair.
    Kept in this process only: run the API as one process per host, or the web app's own lock
    (one refresh at a time per browser) is what prevents the race.
    """

    REMEMBER_SECONDS = 30.0

    def __init__(self) -> None:
        self._pending: dict[str, tuple[float, asyncio.Task[TokenPair | None]]] = {}

    async def refresh(self, refresh_token: str, do: Callable[[str], Awaitable[TokenPair | None]]) -> TokenPair | None:
        now = time.monotonic()
        for key, (started, _) in list(self._pending.items()):
            if now - started > self.REMEMBER_SECONDS:
                del self._pending[key]
        key = security.hash_token(refresh_token)
        entry = self._pending.get(key)
        if entry is None:
            entry = (now, asyncio.ensure_future(do(refresh_token)))
            self._pending[key] = entry
        # shield: one caller giving up (a closed tab) mustn't cancel the others' refresh.
        return await asyncio.shield(entry[1])


shared_refresh = SharedRefresh()
