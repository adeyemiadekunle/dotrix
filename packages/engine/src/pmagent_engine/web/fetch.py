"""Reading web pages safely (docs/agents-v2.md §6.1).

An agent can ask for any URL, so the fetcher treats every one as hostile: http(s) on the
standard ports only, and only public addresses. A hostname is resolved and every address it
resolves to must be public, both before each request (redirects included, each one checked
again) and on the connection actually made (`PublicOnlyTransport` connects to the address it
checked, so a DNS answer that changes in between can't point it at an internal service).
Responses are capped in size and time, robots.txt is respected, and requests to one host are
spaced out. Pages come back as Markdown (`ingest.to_markdown`).
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import ipaddress
import re
import socket
import time
import urllib.robotparser
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx

from ..ingest import UnsupportedDocument, to_markdown

USER_AGENT = "pmagent-research/1.0 (+https://github.com/pmagent)"
ALLOWED_PORTS = frozenset({80, 443})
MAX_REDIRECTS = 5
# A page whose text is shorter than this was probably built by JavaScript.
MIN_TEXT_CHARS = 200

Resolver = Callable[[str, int], Awaitable[list[str]]]

_TYPES = {
    "text/html": ".html",
    "application/xhtml+xml": ".html",
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/markdown": ".md",
}


class FetchError(Exception):
    """A page that couldn't be read. `fallback` says whether another reader (Tavily's extract)
    may try it: never for addresses we refuse or pages robots.txt keeps us out of."""

    def __init__(self, message: str, *, fallback: bool = False) -> None:
        super().__init__(message)
        self.fallback = fallback


class BlockedAddress(FetchError):
    def __init__(self, message: str) -> None:
        super().__init__(message, fallback=False)


@dataclass(frozen=True)
class Page:
    url: str  # what was asked for
    final_url: str  # after redirects
    title: str
    markdown: str
    content_type: str
    published: str | None = None
    via: str = "direct"  # or "tavily"
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.markdown.encode("utf-8")).hexdigest()


def is_public(address: str) -> bool:
    """Whether an IP address is on the public internet (not private, loopback, link-local,
    CGNAT, multicast, reserved, or a cloud metadata address)."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped or ip.sixtofour
        if mapped is not None:
            ip = mapped
    return ip.is_global and not ip.is_multicast


def check_url(url: str) -> tuple[str, int]:
    """(host, port) of a URL we may request, or BlockedAddress. Doesn't resolve the host."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise BlockedAddress(f"Not a valid URL: {url}") from exc
    if parts.scheme not in ("http", "https"):
        raise BlockedAddress("Only http and https pages can be read")
    if parts.username or parts.password:
        raise BlockedAddress("URLs with credentials aren't read")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise BlockedAddress(f"Not a valid URL: {url}")
    port = port or (443 if parts.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise BlockedAddress("Only the standard web ports (80 and 443) are read")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise BlockedAddress("That address isn't on the public internet")
    return host, port


async def system_resolver(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


async def public_addresses(host: str, port: int, resolver: Resolver) -> list[str]:
    """Every address `host` resolves to, if all of them are public; else BlockedAddress."""
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        addresses = [str(literal)]
    else:
        try:
            addresses = await resolver(host, port)
        except OSError as exc:
            raise FetchError(f"Couldn't find {host}") from exc
    if not addresses or not all(is_public(a) for a in addresses):
        raise BlockedAddress("That address isn't on the public internet")
    return addresses


class _PublicOnlyBackend(httpcore.AsyncNetworkBackend):
    """Connects only to public addresses: resolves the host itself, checks every answer, and
    connects to a checked address (TLS still verifies the hostname)."""

    def __init__(self, resolver: Resolver) -> None:
        self._inner = httpcore.AnyIOBackend()
        self._resolver = resolver

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        try:
            addresses = await public_addresses(host, port, self._resolver)
        except FetchError as exc:
            raise httpcore.ConnectError(str(exc)) from exc
        last: Exception | None = None
        for address in addresses:
            try:
                return await self._inner.connect_tcp(
                    address, port, timeout=timeout, local_address=local_address, socket_options=socket_options
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last = exc
        assert last is not None
        raise last

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):  # pragma: no cover
        raise httpcore.ConnectError("Unix sockets aren't allowed")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class PublicOnlyTransport(httpx.AsyncHTTPTransport):
    """httpx's transport over `_PublicOnlyBackend`, ignoring proxy settings from the
    environment (a proxy would make the connection, unchecked)."""

    def __init__(self, resolver: Resolver = system_resolver) -> None:
        super().__init__(trust_env=False)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(trust_env=False),
            max_connections=10,
            keepalive_expiry=5.0,
            network_backend=_PublicOnlyBackend(resolver),
        )


_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_META = re.compile(r"<meta\s[^>]*>", re.I)
_ATTR = re.compile(r"""([\w:-]+)\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""")
_TIME = re.compile(r"""<time[^>]*\sdatetime\s*=\s*["']([^"']+)["']""", re.I)
_PUBLISHED_KEYS = ("article:published_time", "datepublished", "date", "dc.date", "pubdate")
_TITLE_KEYS = ("og:title", "twitter:title")


def _meta(markup: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for tag in _META.findall(markup[:200_000]):
        attrs = {k.lower(): v.strip("\"'") for k, v in _ATTR.findall(tag)}
        key = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
        if key and "content" in attrs:
            found.setdefault(key, html.unescape(attrs["content"]).strip())
    return found


def page_facts(markup: str) -> tuple[str, str | None]:
    """(title, published date) from a page's HTML, when it says."""
    meta = _meta(markup)
    title = next((meta[k] for k in _TITLE_KEYS if meta.get(k)), "")
    if not title and (match := _TITLE.search(markup[:200_000])):
        title = html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    published = next((meta[k] for k in _PUBLISHED_KEYS if meta.get(k)), None)
    if published is None and (match := _TIME.search(markup[:200_000])):
        published = match.group(1)
    return title[:300], (published[:40] if published else None)


def _markdown_title(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()[:300]
    return ""


class PageFetcher:
    """Reads pages for agents. One per run is fine; it keeps robots.txt answers and the time
    of the last request to each host. `transport` and `resolver` are for tests."""

    def __init__(
        self,
        *,
        resolver: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
        max_bytes: int = 3_000_000,
        timeout: float = 20.0,
        min_interval: float = 1.0,
        respect_robots: bool = True,
        user_agent: str = USER_AGENT,
    ) -> None:
        self._resolver = resolver
        self._client = httpx.AsyncClient(
            transport=transport or PublicOnlyTransport(resolver),
            follow_redirects=False,
            trust_env=False,
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": user_agent, "Accept": ", ".join(_TYPES)},
        )
        self._max_bytes = max_bytes
        self._timeout = timeout
        self._min_interval = min_interval
        self._respect_robots = respect_robots
        self._user_agent = user_agent
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch(self, url: str) -> Page:
        try:
            async with asyncio.timeout(self._timeout * 2):
                return await self._fetch(url)
        except TimeoutError as exc:
            raise FetchError("The page took too long to load", fallback=True) from exc

    async def _fetch(self, url: str) -> Page:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            host, port = check_url(current)
            await public_addresses(host, port, self._resolver)
            if not await self._allowed(current):
                raise FetchError("The site's robots.txt asks automated readers not to read this page")
            await self._space_out(host)
            async with self._client.stream("GET", current) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise FetchError("The page redirected nowhere")
                    current = urljoin(current, location)
                    continue
                if response.status_code >= 400:
                    raise FetchError(f"The site answered {response.status_code}", fallback=True)
                body = await self._read(response)
                content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                return await self._page(url, str(response.url), content_type, body, response.encoding)
        raise FetchError("Too many redirects")

    async def _read(self, response: httpx.Response) -> bytes:
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self._max_bytes:
            raise FetchError("The page is too large to read")
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > self._max_bytes:
                raise FetchError("The page is too large to read")
            chunks.append(chunk)
        return b"".join(chunks)

    async def _page(self, url: str, final: str, content_type: str, body: bytes, encoding: str | None) -> Page:
        suffix = _TYPES.get(content_type)
        if suffix is None:
            raise FetchError(f"Can't read {content_type or 'this kind of file'}")
        if suffix in (".txt", ".md"):
            text = body.decode(encoding or "utf-8", errors="replace")
            return Page(url, final, _markdown_title(text), text, content_type)
        try:
            text = await asyncio.to_thread(to_markdown, f"page{suffix}", body)
        except UnsupportedDocument as exc:
            raise FetchError(str(exc), fallback=True) from exc
        title, published = ("", None)
        if suffix == ".html":
            title, published = page_facts(body.decode(encoding or "utf-8", errors="replace"))
            if len(text.strip()) < MIN_TEXT_CHARS:
                raise FetchError("The page has almost no text (it may need JavaScript)", fallback=True)
        return Page(url, final, title or _markdown_title(text), text, content_type, published)

    async def _allowed(self, url: str) -> bool:
        if not self._respect_robots:
            return True
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            self._robots[origin] = await self._load_robots(origin)
        rules = self._robots[origin]
        return True if rules is None else rules.can_fetch(self._user_agent, url)

    async def _load_robots(self, origin: str) -> urllib.robotparser.RobotFileParser | None:
        """RFC 9309: a missing robots.txt (4xx) allows everything; an unreachable one (5xx, or
        no answer) allows nothing. None means allow all."""
        parser = urllib.robotparser.RobotFileParser()
        try:
            response = await self._client.get(f"{origin}/robots.txt")
        except httpx.HTTPError:
            parser.parse(["User-agent: *", "Disallow: /"])
            return parser
        if response.status_code >= 500:
            parser.parse(["User-agent: *", "Disallow: /"])
            return parser
        if response.status_code >= 300:
            return None
        parser.parse(response.text[:500_000].splitlines())
        return parser

    async def _space_out(self, host: str) -> None:
        if self._min_interval <= 0:
            return
        async with self._lock:  # take the host's next slot; wait for it outside the lock
            now = time.monotonic()
            last = self._last.get(host)
            slot = now if last is None else max(now, last + self._min_interval)
            self._last[host] = slot
        if slot > now:
            await asyncio.sleep(slot - now)
