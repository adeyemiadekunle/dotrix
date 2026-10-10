"""Rate limits for endpoints that can be abused anonymously (sign-up, login, password reset,
verification emails): per client IP and per email address.

Sliding-window counters: the current fixed window's count plus the previous window's,
weighted by how much of it still overlaps the last `window` seconds. Cheap (two keys per
limit) and without the burst a plain fixed window allows at its boundary.

- `RedisRateLimiter`: shared by every API process (production).
- `MemoryRateLimiter`: one process only (development without Redis, tests).
- `NoRateLimiter`: off.
"""
from __future__ import annotations

import hashlib
import ipaddress
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import Request

from .settings import Settings


@dataclass(frozen=True)
class Limit:
    name: str  # e.g. "login:email"
    count: int  # attempts allowed...
    window_seconds: int  # ...in any window this long


class RateLimiter(Protocol):
    async def hit(self, limit: Limit, key: str) -> float | None:
        """Count one attempt. None if it's allowed, else the seconds to wait."""
        ...


def _estimate(current: int, previous: int, elapsed: float, window: int) -> float:
    return current + previous * (1 - elapsed / window)


def _retry_after(current: int, previous: int, elapsed: float, limit: Limit) -> float | None:
    """None if this attempt is allowed; otherwise how long until the next one will be (it
    counts too, as rejected attempts do)."""
    window, allowed = limit.window_seconds, limit.count
    if _estimate(current, previous, elapsed, window) <= allowed:
        return None
    room = allowed - (current + 1)
    if room >= 0 and previous:
        # Allowed later in this window, once enough of the previous window's weight has faded.
        return max(1.0, window * (1 - room / previous) - elapsed)
    # Not in this window: wait for it to end, then for its weight to fade in the next.
    return max(1.0, (window - elapsed) + window * (1 - (allowed - 1) / current))


class MemoryRateLimiter:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        # (limit, key, window number) -> (count, when the entry stops mattering)
        self._counts: dict[tuple[str, str, int], tuple[int, float]] = {}

    async def hit(self, limit: Limit, key: str) -> float | None:
        now = self.clock()
        window = limit.window_seconds
        bucket = int(now // window)
        if len(self._counts) > 10_000:
            self._counts = {k: v for k, v in self._counts.items() if v[1] > now}
        count, _ = self._counts.get((limit.name, key, bucket), (0, 0.0))
        current = count + 1
        self._counts[(limit.name, key, bucket)] = (current, (bucket + 2) * window)
        previous, _ = self._counts.get((limit.name, key, bucket - 1), (0, 0.0))
        return _retry_after(current, previous, now - bucket * window, limit)


class RedisRateLimiter:
    def __init__(self, redis: Any, prefix: str = "dotrix:ratelimit", clock: Callable[[], float] = time.time) -> None:
        self.redis, self.prefix, self.clock = redis, prefix, clock

    async def hit(self, limit: Limit, key: str) -> float | None:
        now = self.clock()
        window = limit.window_seconds
        bucket = int(now // window)
        base = f"{self.prefix}:{limit.name}:{key}"
        pipe = self.redis.pipeline()
        pipe.incr(f"{base}:{bucket}")
        pipe.expire(f"{base}:{bucket}", window * 2)
        pipe.get(f"{base}:{bucket - 1}")
        current, _, previous = await pipe.execute()
        return _retry_after(int(current), int(previous or 0), now - bucket * window, limit)


class NoRateLimiter:
    async def hit(self, limit: Limit, key: str) -> float | None:
        return None


def build_rate_limiter(settings: Settings, redis: Any | None) -> RateLimiter:
    if settings.rate_limits == "off":
        return NoRateLimiter()
    if settings.rate_limits == "redis" and redis is not None:
        return RedisRateLimiter(redis)
    return MemoryRateLimiter()  # (redis before the lifespan has connected: memory until then)


def get_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter


def email_key(email: str) -> str:
    """Emails are keyed by a hash, so the limiter's store holds no addresses."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:32]


def client_ip(request: Request, trusted_proxies: list[str]) -> str:
    """The caller's IP. X-Forwarded-For counts only when the direct peer is a trusted proxy
    (e.g. the web app's server): then the client is the rightmost address not a proxy.
    Anyone can send the header, so from any other peer it's ignored."""
    peer = request.client.host if request.client else "unknown"
    trusted = _networks(trusted_proxies)
    if not _in(peer, trusted):
        return peer
    forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
    for address in reversed(forwarded):
        if not _in(address, trusted):
            return address
    return forwarded[0] if forwarded else peer


def _networks(entries: list[str]) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    return [ipaddress.ip_network(entry, strict=False) for entry in entries]


def _in(address: str, networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network]) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in networks)


def wait_phrase(seconds: float) -> str:
    minutes = max(1, math.ceil(seconds / 60))
    return "a minute" if minutes == 1 else f"{minutes} minutes"
