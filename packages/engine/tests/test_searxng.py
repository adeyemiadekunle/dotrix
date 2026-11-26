from urllib.parse import parse_qs

import httpx
import pytest

from dotrix_engine.web.search import SearchUnavailable, SearxngSearch


@pytest.mark.asyncio
async def test_searxng_posts_json_format_and_filters_results():
    def serve(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST" and request.url.path == "/instance/search"
        assert parse_qs(request.content.decode()) == {"q": ["Python releases"], "format": ["json"],
                                                       "categories": ["general"], "time_range": ["day"]}
        return httpx.Response(200, json={"results": [
            {"url": "https://python.org.example/", "title": "Wrong host"},
            {"url": "file:///etc/hosts"},
            {"url": "https://docs.python.org/", "title": "Docs", "content": "Official documentation"},
            {"url": "https://docs.python.org/", "title": "Duplicate"},
        ]})

    search = SearxngSearch("http://searxng:8080/instance/", transport=httpx.MockTransport(serve))
    hits = await search.search("Python releases", recency_days=1, include_domains=["python.org"])
    assert [(hit.url, hit.title, hit.snippet) for hit in hits] == [
        ("https://docs.python.org/", "Docs", "Official documentation"),
    ]


@pytest.mark.asyncio
async def test_searxng_does_not_follow_redirects_or_leak_endpoint_details():
    def serve(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "searxng"
        return httpx.Response(302, headers={"Location": "https://example.com/"})

    search = SearxngSearch("http://searxng:8080", transport=httpx.MockTransport(serve))
    with pytest.raises(SearchUnavailable, match="^Web search is unavailable right now$"):
        await search.search("Python releases")
