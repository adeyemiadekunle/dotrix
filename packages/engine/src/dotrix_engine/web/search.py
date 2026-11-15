"""Web search for agents (docs/architecture.md): one provider interface, SearXNG behind
it, and a fake for tests. Results carry what a source record needs; pages are read with
`fetch.PageFetcher`, not taken from the provider.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from .fetch import Page

logger = logging.getLogger(__name__)

Depth = Literal["basic", "advanced"]


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
        return Page(url, url, "", text, "text/markdown", via="extractor") if text else None
