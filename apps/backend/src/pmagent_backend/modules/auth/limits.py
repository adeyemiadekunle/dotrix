"""Rate limits on the auth endpoints anyone can call: per client IP (slows one machine trying
many accounts) and per email address (slows many machines trying one account, and stops
anyone flooding an inbox)."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from pmagent_backend.api.deps import SettingsDep
from pmagent_backend.core.errors import TooManyRequests
from pmagent_backend.core.ratelimit import (
    Limit,
    RateLimiter,
    client_ip,
    email_key,
    get_rate_limiter,
    wait_phrase,
)

HOUR, QUARTER_HOUR = 3600, 900

SIGNUP = (Limit("signup:ip", 10, HOUR), Limit("signup:email", 5, HOUR))
LOGIN = (Limit("login:ip", 50, QUARTER_HOUR), Limit("login:email", 10, QUARTER_HOUR))
PASSWORD_RESET = (Limit("reset:ip", 20, HOUR), Limit("reset:email", 5, HOUR))
MAGIC_LINK = (Limit("magic:ip", 20, HOUR), Limit("magic:email", 5, HOUR))
VERIFY_RESEND = (Limit("verify:ip", 20, HOUR), Limit("verify:email", 5, HOUR))


class Throttle:
    def __init__(self, limiter: RateLimiter, ip: str) -> None:
        self.limiter, self.ip = limiter, ip

    async def __call__(self, limits: tuple[Limit, Limit], email: str) -> None:
        """Count an attempt against both limits; 429 if either is used up."""
        by_ip, by_email = limits
        for limit, key in ((by_ip, self.ip), (by_email, email_key(email))):
            wait = await self.limiter.hit(limit, key)
            if wait is not None:
                raise TooManyRequests(f"Too many attempts. Try again in {wait_phrase(wait)}.", wait)


def get_throttle(
    request: Request, settings: SettingsDep, limiter: Annotated[RateLimiter, Depends(get_rate_limiter)]
) -> Throttle:
    return Throttle(limiter, client_ip(request, settings.trusted_proxies))


ThrottleDep = Annotated[Throttle, Depends(get_throttle)]
