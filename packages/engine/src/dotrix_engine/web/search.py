"""Web search for agents (docs/agents-v2.md §6.1, D3): one provider interface, Tavily behind
it, and a fake for tests. Results carry what a source record needs; pages are read with
`fetch.PageFetcher`, not taken from the provider.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx

from .fetch import Page

logger = logging.getLogger(__name__)

Depth = Literal["basic", "advanced"]
TAVILY_URL = "https://api.tavily.com"
# Tavily's prices in credits: a search by depth, and reading pages (per five, on success).
SEARCH_CREDITS: dict[str, int] = {"basic": 1, "advanced": 2}
EXTRACT_CREDITS = 1


class SearchUnavailable(Exception):
    """Search can't be used right now (no credits left, a bad key, the provider down). The
    message is safe to show the agent; it never contains the key."""


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str
    snippet: str
    published: str | None = None
    score: float | None = None


class SearchProvider(Protocol):
    name: str

    async def search(
        self,
        query: str,
        *,
        recency_days: int | None = None,
        include_domains: Sequence[str] = (),
        exclude_domains: Sequence[str] = (),
        limit: int = 5,
        depth: Depth = "basic",
    ) -> list[SearchHit]: ...


class PageExtractor(Protocol):
    """Reads a page from the provider's side, for pages our fetcher can't (JavaScript-only,
    blocking automated readers by status). None when it couldn't either."""

    async def extract(self, url: str) -> Page | None: ...


def _time_range(recency_days: int | None) -> str | None:
    if recency_days is None or recency_days <= 0:
        return None
    for days, name in ((1, "day"), (7, "week"), (31, "month"), (366, "year")):
        if recency_days <= days:
            return name
    return None


class TavilySearch:
    """Tavily's search and extract APIs (https://docs.tavily.com). One retry on rate limits and
    server errors; a bad key or an exhausted plan is `SearchUnavailable`."""

    name = "tavily"

    def __init__(self, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None,
                 base_url: str = TAVILY_URL, timeout: float = 30.0, retry_after: float = 1.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            transport=transport,
            timeout=httpx.Timeout(timeout),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        self._retry_after = retry_after

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(
        self,
        query: str,
        *,
        recency_days: int | None = None,
        include_domains: Sequence[str] = (),
        exclude_domains: Sequence[str] = (),
        limit: int = 5,
        depth: Depth = "basic",
    ) -> list[SearchHit]:
        body: dict[str, object] = {
            "query": query[:400],
            "search_depth": depth if depth in SEARCH_CREDITS else "basic",
            "topic": "general",
            "max_results": max(1, min(limit, 10)),
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }
        if time_range := _time_range(recency_days):
            body["time_range"] = time_range
        if include_domains:
            body["include_domains"] = list(include_domains)[:20]
        if exclude_domains:
            body["exclude_domains"] = list(exclude_domains)[:20]
        data = await self._post("/search", body)
        hits: list[SearchHit] = []
        for item in data.get("results") or []:
            if not isinstance(item, Mapping) or not item.get("url"):
                continue
            score = item.get("score")
            hits.append(SearchHit(
                url=str(item["url"]),
                title=str(item.get("title") or ""),
                snippet=str(item.get("content") or ""),
                published=str(item["published_date"]) if item.get("published_date") else None,
                score=float(score) if isinstance(score, int | float) else None,
            ))
        return hits

    async def extract(self, url: str) -> Page | None:
        data = await self._post("/extract", {"urls": [url], "extract_depth": "basic", "format": "markdown"})
        for item in data.get("results") or []:
            text = str(item.get("raw_content") or "") if isinstance(item, Mapping) else ""
            if text.strip():
                return Page(url, str(item.get("url") or url), "", text, "text/markdown", via="tavily")
        return None

    async def _post(self, path: str, body: dict[str, object]) -> dict:
        for attempt in (1, 2):
            try:
                response = await self._client.post(path, json=body)
            except httpx.HTTPError as exc:
                if attempt == 1:
                    await asyncio.sleep(self._retry_after)
                    continue
                logger.warning("tavily.unreachable", extra={"path": path, "error": exc.__class__.__name__})
                raise SearchUnavailable("Web search is unavailable right now") from exc
            status = response.status_code
            if status == 200:
                data = response.json()
                return data if isinstance(data, dict) else {}
            if (status == 429 or status >= 500) and attempt == 1:
                await asyncio.sleep(self._retry_after)
                continue
            logger.warning("tavily.failed", extra={"path": path, "status": status})
            if status in (401, 403):
                raise SearchUnavailable("Web search isn't set up correctly (the key was refused)")
            if status in (432, 433):
                raise SearchUnavailable("Web search has used up its credits for now")
            if status == 400:
                raise SearchUnavailable("Web search couldn't run that query; try rephrasing it")
            raise SearchUnavailable("Web search is unavailable right now")
        raise SearchUnavailable("Web search is unavailable right now")  # pragma: no cover


class FakeSearch:
    """Canned results for tests and evals: each query gets the hits of the first key it
    contains (case-insensitive), else `default`. Records every query it was asked."""

    name = "fake"

    def __init__(self, results: Mapping[str, Sequence[SearchHit]] | None = None,
                 default: Sequence[SearchHit] = (), pages: Mapping[str, str] | None = None) -> None:
        self._results = {k.lower(): list(v) for k, v in (results or {}).items()}
        self._default = list(default)
        self._pages = dict(pages or {})
        self.queries: list[dict[str, object]] = []

    async def search(
        self,
        query: str,
        *,
        recency_days: int | None = None,
        include_domains: Sequence[str] = (),
        exclude_domains: Sequence[str] = (),
        limit: int = 5,
        depth: Depth = "basic",
    ) -> list[SearchHit]:
        self.queries.append({"query": query, "recency_days": recency_days,
                             "include_domains": list(include_domains), "depth": depth})
        lowered = query.lower()
        hits = next((v for k, v in self._results.items() if k in lowered), self._default)
        return list(hits)[:limit]

    async def extract(self, url: str) -> Page | None:
        text = self._pages.get(url)
        return Page(url, url, "", text, "text/markdown", via="tavily") if text else None
