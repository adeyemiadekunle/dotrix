"""Tavily behind the search interface: the request we send, the results we keep, and errors
that never leak the key (docs/agents-v2.md §6.1, D3)."""
import json

import httpx
import pytest

from pmagent_engine.web.search import FakeSearch, SearchHit, SearchUnavailable, TavilySearch

KEY = "tvly-secret-key"


def tavily(handler) -> TavilySearch:
    return TavilySearch(KEY, transport=httpx.MockTransport(handler), retry_after=0)


async def test_the_search_request() -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"results": [
            {"url": "https://www.gov.uk/vat", "title": "VAT", "content": "20%", "score": 0.9,
             "published_date": "2026-01-01"},
            {"title": "no url, skipped"},
        ]})

    hits = await tavily(handler).search(
        "uk vat rate", recency_days=30, include_domains=["gov.uk"], limit=50, depth="advanced"
    )
    assert hits == [SearchHit("https://www.gov.uk/vat", "VAT", "20%", "2026-01-01", 0.9)]
    request = sent[0]
    assert str(request.url) == "https://api.tavily.com/search"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(request.content)
    assert body["query"] == "uk vat rate"
    assert body["search_depth"] == "advanced" and body["max_results"] == 10
    assert body["time_range"] == "month" and body["include_domains"] == ["gov.uk"]
    assert body["include_raw_content"] is False and body["include_answer"] is False


@pytest.mark.parametrize(("days", "expected"), [(None, None), (1, "day"), (5, "week"), (90, "year"), (900, None)])
async def test_recency_maps_to_a_time_range(days, expected) -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"results": []})

    await tavily(handler).search("q", recency_days=days)
    assert bodies[0].get("time_range") == expected


async def test_rate_limits_and_server_errors_are_retried_once() -> None:
    answers = iter([httpx.Response(429), httpx.Response(200, json={"results": []})])
    assert await tavily(lambda r: next(answers)).search("q") == []

    with pytest.raises(SearchUnavailable, match="unavailable"):
        await tavily(lambda r: httpx.Response(502)).search("q")


@pytest.mark.parametrize(("status", "message"), [(401, "key was refused"), (432, "credits"), (433, "credits"), (400, "rephras")])
async def test_errors_are_safe_to_show_the_agent(status: int, message: str, caplog) -> None:
    with pytest.raises(SearchUnavailable, match=message) as caught:
        await tavily(lambda r: httpx.Response(status, json={"detail": {"error": KEY}})).search("q")
    assert KEY not in str(caught.value)
    assert KEY not in caplog.text


async def test_extract_returns_markdown_from_tavily() -> None:
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"results": [{"url": "https://app.example/", "raw_content": "# App\n\nText"}]})

    page = await tavily(handler).extract("https://app.example/")
    assert page is not None and page.markdown == "# App\n\nText" and page.via == "tavily"
    assert sent[0] == {"urls": ["https://app.example/"], "extract_depth": "basic", "format": "markdown"}

    empty = tavily(lambda r: httpx.Response(200, json={"results": [], "failed_results": [{"url": "x"}]}))
    assert await empty.extract("https://app.example/") is None


async def test_fake_search_matches_by_phrase_and_records_queries() -> None:
    hit = SearchHit("https://example.com", "Example", "text")
    fake = FakeSearch({"vat": [hit]})
    assert await fake.search("UK VAT rate", recency_days=7) == [hit]
    assert await fake.search("something else") == []
    assert fake.queries[0]["recency_days"] == 7
