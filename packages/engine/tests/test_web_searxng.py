import httpx
import pytest

from dotrix_engine.web.search import SearchUnavailable
from dotrix_engine.web.searxng import SearxngSearch


async def test_domain_filters_cannot_be_bypassed_by_search_results():
    def serve(request):
        assert request.url.path == "/search" and request.url.params["format"] == "json"
        return httpx.Response(200, json={"results": [
            {"url": "https://gov.uk.evil.example/a"}, {"url": "https://gov.uk/a", "title": "Evidence"},
            {"url": "https://gov.uk/a"}, {"url": "https://blocked.gov.uk/a"}, {"url": "file:///etc/passwd"},
        ]})
    provider = SearxngSearch("http://search:8080", transport=httpx.MockTransport(serve))
    try:
        hits = await provider.search("query", include_domains=["gov.uk"], exclude_domains=["blocked.gov.uk"])
        assert [h.url for h in hits] == ["https://gov.uk/a"]
    finally:
        await provider.aclose()


@pytest.mark.parametrize("response", [httpx.Response(403, text="private server detail"),
                                     httpx.Response(200, text="not JSON"), httpx.Response(200, json=[])])
async def test_service_failure_is_visible_without_returning_private_response(response):
    provider = SearxngSearch("http://search:8080", transport=httpx.MockTransport(lambda _: response))
    try:
        with pytest.raises(SearchUnavailable, match="SearXNG") as caught:
            await provider.search("query")
        assert "private server detail" not in str(caught.value)
    finally:
        await provider.aclose()


async def test_upstream_failures_are_not_reported_as_no_matches():
    provider = SearxngSearch("http://search:8080", transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"results": [], "unresponsive_engines": [["google", "SSL error"]]})))
    try:
        with pytest.raises(SearchUnavailable, match="upstream"):
            await provider.search("query")
    finally:
        await provider.aclose()
