from starlette.requests import Request

from pmagent_backend.core.ratelimit import (
    Limit,
    MemoryRateLimiter,
    client_ip,
    email_key,
    wait_phrase,
)


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


LIMIT = Limit("login:email", 3, 60)


async def test_allows_the_limit_then_says_how_long_to_wait() -> None:
    clock = Clock(60 * 20_000 + 20)  # 20s into a window
    limiter = MemoryRateLimiter(clock)
    assert [await limiter.hit(LIMIT, "a") for _ in range(3)] == [None, None, None]
    wait = await limiter.hit(LIMIT, "a")
    assert wait is not None and 40 <= wait <= 60
    # Other keys and other limits are counted separately.
    assert await limiter.hit(LIMIT, "b") is None
    assert await limiter.hit(Limit("signup:email", 3, 60), "a") is None


async def test_the_previous_window_still_counts_while_it_fades() -> None:
    clock = Clock(60 * 20_000 + 50)
    limiter = MemoryRateLimiter(clock)
    for _ in range(3):
        await limiter.hit(LIMIT, "a")
    # 15s into the next window, 75% of the previous window's 3 attempts still count.
    clock.now = 60 * 20_001 + 15
    wait = await limiter.hit(LIMIT, "a")  # 1 + 3 * 0.75 = 3.25 > 3
    assert wait is not None and wait < 45
    # Once enough of it has faded, attempts are allowed again.
    clock.now = 60 * 20_001 + 50
    assert await limiter.hit(LIMIT, "a") is None  # 2 + 3 * (10/60) = 2.5


async def test_windows_long_past_are_forgotten() -> None:
    clock = Clock(60 * 20_000)
    limiter = MemoryRateLimiter(clock)
    for _ in range(4):
        await limiter.hit(LIMIT, "a")
    clock.now += 180
    assert await limiter.hit(LIMIT, "a") is None


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


def test_forwarded_for_is_believed_only_from_trusted_proxies() -> None:
    trusted = ["127.0.0.1", "10.0.0.0/8"]
    assert client_ip(_request("203.0.113.9"), trusted) == "203.0.113.9"
    # Anyone can send the header: from an untrusted peer it's ignored.
    assert client_ip(_request("203.0.113.9", "198.51.100.1"), trusted) == "203.0.113.9"
    # Through the web app: the client is the rightmost address that isn't a proxy, so an
    # address the client made up (leftmost) doesn't count.
    assert client_ip(_request("127.0.0.1", "1.2.3.4, 198.51.100.7, 10.1.2.3"), trusted) == "198.51.100.7"
    assert client_ip(_request("127.0.0.1"), trusted) == "127.0.0.1"


def test_emails_are_keyed_by_hash_ignoring_case() -> None:
    assert email_key("Ada@Example.com ") == email_key("ada@example.com")
    assert "ada" not in email_key("ada@example.com")


def test_wait_phrase() -> None:
    assert wait_phrase(5) == "a minute"
    assert wait_phrase(61) == "2 minutes"
    assert wait_phrase(900) == "15 minutes"
