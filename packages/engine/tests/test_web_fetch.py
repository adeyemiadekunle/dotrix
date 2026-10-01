"""Reading pages safely: only public addresses (checked again on every redirect and on the
connection made), standard ports, capped size and time, robots.txt (docs/agents-v2.md §6.1)."""
import asyncio

import httpx
import pytest

from pmagent_engine.web.fetch import (
    BlockedAddress,
    FetchError,
    PageFetcher,
    PublicOnlyTransport,
    check_url,
    is_public,
    page_facts,
)

PUBLIC = "93.184.215.14"
ARTICLE = (
    "<html><head><title>VAT rates</title>"
    '<meta property="article:published_time" content="2026-03-01T09:00:00Z"></head>'
    "<body><h1>VAT rates</h1><p>" + "The standard rate of VAT is 20%. " * 20 + "</p></body></html>"
)


def resolver_for(answers: dict[str, list[str]]):
    async def resolve(host: str, port: int) -> list[str]:
        return answers.get(host, [PUBLIC])

    return resolve


def fetcher(handler, answers: dict[str, list[str]] | None = None, **kwargs) -> PageFetcher:
    kwargs.setdefault("min_interval", 0)
    kwargs.setdefault("respect_robots", False)
    return PageFetcher(resolver=resolver_for(answers or {}), transport=httpx.MockTransport(handler), **kwargs)


def html(body: str = ARTICLE, status: int = 200, **headers: str) -> httpx.Response:
    return httpx.Response(status, content=body.encode(), headers={"content-type": "text/html; charset=utf-8", **headers})


@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.0.0.5", "172.16.3.4", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0",
    "224.0.0.1", "::1", "fc00::1", "fe80::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "2002:7f00:0001::1",
    "fd00:ec2::254", "not-an-ip",
])
def test_private_and_special_addresses_are_not_public(address: str) -> None:
    assert not is_public(address)


@pytest.mark.parametrize("address", ["93.184.215.14", "8.8.8.8", "2606:4700:4700::1111"])
def test_public_addresses_are(address: str) -> None:
    assert is_public(address)


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.com/x", "gopher://example.com", "javascript:alert(1)",
    "http://example.com:8080/", "https://example.com:22/", "http://user:pw@example.com/",
    "http://localhost/", "http://api.internal/", "http://printer.local/", "http:///nohost",
])
def test_urls_we_never_request(url: str) -> None:
    with pytest.raises(BlockedAddress):
        check_url(url)


def test_standard_urls_are_fine() -> None:
    assert check_url("https://www.gov.uk/vat") == ("www.gov.uk", 443)
    assert check_url("http://example.com/a?b=c#d") == ("example.com", 80)


async def test_reads_a_page_as_markdown_with_its_title_and_date() -> None:
    page = await fetcher(lambda request: html()).fetch("https://example.com/vat")
    assert page.title == "VAT rates"
    assert page.published == "2026-03-01T09:00:00Z"
    assert "standard rate of VAT is 20%" in page.markdown
    assert page.final_url == "https://example.com/vat" and page.via == "direct"
    assert len(page.content_hash) == 64


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://[::1]/", "http://169.254.169.254/latest/meta-data"])
async def test_ip_literals_that_arent_public_are_refused_before_any_request(url: str) -> None:
    requests: list[httpx.Request] = []
    with pytest.raises(BlockedAddress):
        await fetcher(lambda r: requests.append(r) or html()).fetch(url)
    assert requests == []


async def test_a_host_that_resolves_to_a_private_address_is_refused() -> None:
    requests: list[httpx.Request] = []
    with pytest.raises(BlockedAddress):
        await fetcher(lambda r: requests.append(r) or html(), {"evil.example": ["10.0.0.7"]}).fetch("http://evil.example/")
    assert requests == []


async def test_one_private_answer_among_public_ones_is_enough_to_refuse() -> None:
    with pytest.raises(BlockedAddress):
        await fetcher(lambda r: html(), {"mixed.example": [PUBLIC, "127.0.0.1"]}).fetch("http://mixed.example/")


@pytest.mark.parametrize("location", [
    "http://127.0.0.1/admin", "http://internal.example/", "file:///etc/passwd", "http://example.com:6379/",
])
async def test_redirects_are_checked_again(location: str) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": location})

    with pytest.raises(BlockedAddress):
        await fetcher(handler, {"internal.example": ["192.168.0.10"]}).fetch("https://example.com/start")
    assert seen == ["https://example.com/start"]


async def test_relative_redirects_are_followed_up_to_a_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/final":
            return html()
        return httpx.Response(301, headers={"location": "/final"})

    page = await fetcher(handler).fetch("https://example.com/old")
    assert page.final_url == "https://example.com/final"

    with pytest.raises(FetchError, match="Too many redirects"):
        await fetcher(lambda r: httpx.Response(302, headers={"location": "/again"})).fetch("https://example.com/")


async def test_oversized_pages_are_refused() -> None:
    with pytest.raises(FetchError, match="too large"):
        await fetcher(lambda r: html("x" * 2000), max_bytes=1000).fetch("https://example.com/")
    declared = httpx.Response(200, headers={"content-type": "text/html", "content-length": "99999999"}, content=b"x")
    with pytest.raises(FetchError, match="too large"):
        await fetcher(lambda r: declared, max_bytes=1000).fetch("https://example.com/")


async def test_slow_pages_time_out() -> None:
    class Slow(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"<html>"
            await asyncio.sleep(5)
            yield b"</html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, stream=Slow())

    with pytest.raises(FetchError, match="too long") as caught:
        await fetcher(handler, timeout=0.1).fetch("https://example.com/")
    assert caught.value.fallback


async def test_other_content_types_are_refused() -> None:
    response = httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=b"\x00\x01")
    with pytest.raises(FetchError, match="Can't read"):
        await fetcher(lambda r: response).fetch("https://example.com/file.bin")


async def test_pages_built_by_javascript_can_fall_back() -> None:
    with pytest.raises(FetchError, match="JavaScript") as caught:
        await fetcher(lambda r: html("<html><body><div id=root></div></body></html>")).fetch("https://app.example/")
    assert caught.value.fallback


async def test_errors_from_the_site_can_fall_back_but_blocked_addresses_cannot() -> None:
    with pytest.raises(FetchError) as caught:
        await fetcher(lambda r: html(status=403)).fetch("https://example.com/")
    assert caught.value.fallback
    with pytest.raises(BlockedAddress) as blocked:
        await fetcher(lambda r: html()).fetch("http://10.1.1.1/")
    assert not blocked.value.fallback


async def test_plain_text_and_markdown_are_read_as_is() -> None:
    response = httpx.Response(200, headers={"content-type": "text/markdown"}, content=b"# Changelog\n\n- 2.0")
    page = await fetcher(lambda r: response).fetch("https://example.com/CHANGELOG.md")
    assert page.title == "Changelog" and page.markdown.startswith("# Changelog")


async def test_robots_txt_is_respected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
        return html()

    reader = fetcher(handler, respect_robots=True)
    assert (await reader.fetch("https://example.com/public")).title == "VAT rates"
    with pytest.raises(FetchError, match="robots.txt") as caught:
        await reader.fetch("https://example.com/private/x")
    assert not caught.value.fallback


async def test_robots_txt_missing_allows_and_unreachable_refuses() -> None:
    def missing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404) if request.url.path == "/robots.txt" else html()

    assert (await fetcher(missing, respect_robots=True).fetch("https://example.com/")).title

    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503) if request.url.path == "/robots.txt" else html()

    with pytest.raises(FetchError, match="robots.txt"):
        await fetcher(broken, respect_robots=True).fetch("https://example.com/")


async def test_requests_to_one_host_are_spaced_out() -> None:
    reader = fetcher(lambda r: html(), min_interval=0.2)
    loop = asyncio.get_running_loop()
    start = loop.time()
    await asyncio.gather(reader.fetch("https://example.com/a"), reader.fetch("https://example.com/b"))
    assert loop.time() - start >= 0.18


async def test_the_real_transport_connects_only_to_public_addresses() -> None:
    """No mock: the connection itself is refused for a name that resolves privately, so a DNS
    answer that changes after the first check can't reach an internal service."""
    calls: list[str] = []

    async def rebinding(host: str, port: int) -> list[str]:
        # By the time the connection is made, the name answers with an internal address.
        calls.append(host)
        return ["127.0.0.1"]

    async with httpx.AsyncClient(transport=PublicOnlyTransport(rebinding), trust_env=False) as client:
        with pytest.raises(httpx.ConnectError, match="public internet"):
            await client.get("http://rebind.example/")
        with pytest.raises(httpx.ConnectError, match="public internet"):
            await client.get("http://127.0.0.1:80/")
    assert calls == ["rebind.example"]


def test_page_facts_from_markup() -> None:
    assert page_facts('<title> A &amp; B </title>') == ("A & B", None)
    assert page_facts('<meta property="og:title" content="OG"><time datetime="2025-01-02">x</time>') == ("OG", "2025-01-02")
