"""Search through an operator-configured SearXNG instance; pages use the shared safe reader."""
from collections.abc import Sequence
from urllib.parse import urlsplit

import httpx

from .search import Depth, SearchHit, SearchUnavailable


class SearxngSearch:
    name = "searxng"

    def __init__(self, base_url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        url = urlsplit(base_url)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("SearXNG needs an HTTP(S) service URL without credentials, query or fragment")
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/") + "/", timeout=30,
                                         transport=transport, follow_redirects=False)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, query: str, *, recency_days: int | None = None,
                     include_domains: Sequence[str] = (), exclude_domains: Sequence[str] = (),
                     limit: int = 5, depth: Depth = "basic") -> list[SearchHit]:
        params = {"q": query[:400], "format": "json", "categories": "general"}
        if recency_days and recency_days > 0:
            params["time_range"] = "day" if recency_days <= 1 else "month" if recency_days <= 31 else "year"
        try:
            response = await self._client.get("search", params=params)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                raise ValueError("Invalid search response")
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchUnavailable("Web search is unavailable; check the SearXNG service and JSON format configuration") from exc

        def matches(host: str, domains: Sequence[str]) -> bool:
            return any(host == d.strip().lower().rstrip(".") or host.endswith("." + d.strip().lower().rstrip("."))
                       for d in domains if d.strip())

        hits: list[SearchHit] = []
        seen: set[str] = set()
        for item in data["results"]:
            if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                continue
            address = item["url"]
            try:
                url = urlsplit(address)
                host = (url.hostname or "").lower().rstrip(".")
            except ValueError:
                continue
            if url.scheme not in ("https", "http") or not host or url.username or url.password:
                continue
            if address in seen or matches(host, exclude_domains) or (include_domains and not matches(host, include_domains)):
                continue
            seen.add(address)
            hits.append(SearchHit(address, str(item.get("title") or "")[:1000], str(item.get("content") or "")[:8000],
                                  str(item["publishedDate"]) if item.get("publishedDate") else None))
            if len(hits) >= max(1, min(limit, 10)):
                break
        if not hits and data.get("unresponsive_engines"):
            raise SearchUnavailable("Web search could not return results because upstream search engines are unavailable")
        return hits
