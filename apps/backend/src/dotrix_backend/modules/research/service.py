"""Research on the web for agent runs (docs/agents-v2.md §6).

`WebResearch` (one per process, from settings) gives each step of a run its web tools
(`dotrix_engine.web`): sources saved to `research_sources` after every call, so their ids stay
the same when the run resumes; pages cached per workspace in `web_pages` for a day; searches,
page reads, and Tavily credits limited per run and per workspace per day. `check_report` checks
a report's claims against the pages its sources were read from.
"""
from __future__ import annotations

import functools
import hashlib
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import Integer, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils.compat import uuid7

from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.agents.models import AgentRun
from dotrix_backend.modules.agents.storage_backend import SessionFactory
from dotrix_engine.web import (
    FakeSearch,
    Page,
    PageFetcher,
    SearchHit,
    SearchProvider,
    Source,
    SourceLog,
    TavilySearch,
    WebLimits,
    WebUsage,
    build_web_tools,
    check_claim,
    url_key,
)
from dotrix_engine.web.search import PageExtractor

from .models import ResearchSource, WebPage

logger = logging.getLogger(__name__)

CACHE_FOR = timedelta(days=1)  # a page read in the last day isn't fetched again
KEEP_PAGES_FOR = timedelta(days=30)  # then the cleanup job drops it


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(url: str) -> str:
    return hashlib.sha256(url_key(url).encode("utf-8")).hexdigest()


def _source(row: ResearchSource) -> Source:
    return Source(
        label=row.label, url=row.url, title=row.title, host=row.host, tier=row.tier,  # type: ignore[arg-type]
        kind=row.kind, snippet=row.snippet, published=row.published, fetched_at=row.fetched_at,
        content_hash=row.content_hash, via=row.via, flagged=tuple(row.flagged or ()),
    )


class WorkspacePageCache:
    """`dotrix_engine.web.PageCache` over `web_pages`, for one workspace."""

    def __init__(self, session_factory: SessionFactory, workspace_id: uuid.UUID) -> None:
        self._sessions = session_factory
        self._workspace_id = workspace_id

    async def get(self, url: str) -> Page | None:
        async with self._sessions() as session:
            row = await session.scalar(select(WebPage).where(
                WebPage.workspace_id == self._workspace_id, WebPage.url_key == _hash(url),
                WebPage.fetched_at >= _now() - CACHE_FOR,
            ))
        if row is None:
            return None
        return Page(url, row.final_url, row.title, row.markdown, row.content_type, row.published, row.via, row.fetched_at)

    async def put(self, page: Page) -> None:
        values = {
            "url": page.url, "final_url": page.final_url, "title": page.title[:300], "markdown": page.markdown,
            "content_type": page.content_type[:64], "published": page.published, "content_hash": page.content_hash,
            "via": page.via, "fetched_at": page.fetched_at,
        }
        async with self._sessions() as session:
            await session.execute(
                insert(WebPage)
                .values(id=uuid7(), workspace_id=self._workspace_id, url_key=_hash(page.url), **values)
                .on_conflict_do_update(index_elements=["workspace_id", "url_key"], set_=values)
            )
            await session.commit()


class RunSources:
    """A run's `SourceLog`, saved after every web tool call (`flush`)."""

    def __init__(self, session_factory: SessionFactory, *, workspace_id: uuid.UUID, project_id: uuid.UUID,
                 run_id: uuid.UUID) -> None:
        self._sessions = session_factory
        self._ids = {"workspace_id": workspace_id, "project_id": project_id, "run_id": run_id}
        self._dirty: dict[str, Source] = {}
        self.log = SourceLog()

    async def load(self) -> SourceLog:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(ResearchSource).where(ResearchSource.run_id == self._ids["run_id"]).order_by(ResearchSource.number)
            )
            existing = [_source(row) for row in rows]
        self.log = SourceLog(existing, on_change=lambda source: self._dirty.__setitem__(source.label, source))
        return self.log

    async def flush(self) -> None:
        if not self._dirty:
            return
        changed, self._dirty = list(self._dirty.values()), {}
        now = _now()
        async with self._sessions() as session:
            for source in changed:
                values = {
                    "url": source.url, "title": source.title[:300], "host": source.host[:255], "tier": source.tier,
                    "kind": source.kind, "snippet": source.snippet, "published": source.published,
                    "fetched_at": source.fetched_at, "content_hash": source.content_hash, "via": source.via,
                    "flagged": list(source.flagged), "updated_at": now,
                }
                await session.execute(
                    insert(ResearchSource)
                    .values(id=uuid7(), number=int(source.label[1:]), created_at=now, **self._ids, **values)
                    .on_conflict_do_update(index_elements=["run_id", "number"], set_=values)
                )
            await session.commit()


def _flushing(tool: Callable, sources: RunSources) -> Callable:
    """The tool, saving the sources it noted as soon as it returns (same name, arguments, and
    description, which the model sees)."""

    @functools.wraps(tool)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await tool(*args, **kwargs)
        finally:
            await sources.flush()

    return wrapper


@dataclass
class RunWeb:
    """One step's web tools, and what they used (recorded on the run with its tokens)."""

    tools: list[Callable]
    usage: WebUsage
    fetcher: PageFetcher
    sources: RunSources

    async def aclose(self) -> None:
        await self.sources.flush()
        await self.fetcher.aclose()


async def credits_used_today(session: AsyncSession, workspace_id: uuid.UUID) -> int:
    """Tavily credits the workspace's runs used since midnight (UTC)."""
    midnight = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    used = await session.scalar(
        select(func.coalesce(func.sum(AgentRun.usage["web"]["credits"].astext.cast(Integer)), 0)).where(
            AgentRun.workspace_id == workspace_id, AgentRun.updated_at >= midnight
        )
    )
    return int(used or 0)


def usage_totals(usage: WebUsage) -> dict[str, Any]:
    return {"searches": usage.searches, "fetches": usage.fetches, "credits": usage.credits,
            "flagged": list(usage.flagged)}


@dataclass
class WebResearch:
    """The web tools' setup for this process. `search` None: the model's built-in search does
    the searching, and agents still read pages with `fetch_page`."""

    search: SearchProvider | None = None
    extractor: PageExtractor | None = None
    max_searches: int = 10
    max_fetches: int = 20
    daily_credits: int = 0  # Tavily credits per workspace per day; 0: no limit
    fetcher_factory: Callable[[], PageFetcher] = field(default=PageFetcher)

    async def for_run(
        self, session_factory: SessionFactory, *, workspace_id: uuid.UUID, project_id: uuid.UUID,
        run_id: uuid.UUID, prior: dict[str, Any] | None,
    ) -> RunWeb:
        """The tools for one step of a run; `prior` is what its earlier steps used (the run's
        usage["web"]), so limits cover the whole run."""
        prior = prior or {}
        usage = WebUsage(
            searches=int(prior.get("searches", 0)), fetches=int(prior.get("fetches", 0)),
            credits=int(prior.get("credits", 0)), flagged=list(prior.get("flagged") or []),
        )
        max_credits = None
        if self.daily_credits:
            async with session_factory() as session:
                left = max(0, self.daily_credits - await credits_used_today(session, workspace_id))
            # The run's own earlier credits are in today's total already (when they were today).
            max_credits = left + usage.credits
        sources = RunSources(session_factory, workspace_id=workspace_id, project_id=project_id, run_id=run_id)
        log = await sources.load()
        fetcher = self.fetcher_factory()
        tools = build_web_tools(
            search=self.search, fetcher=fetcher, sources=log, usage=usage,
            limits=WebLimits(max_searches=self.max_searches, max_fetches=self.max_fetches, max_credits=max_credits),
            cache=WorkspacePageCache(session_factory, workspace_id), extractor=self.extractor,
        )
        return RunWeb([_flushing(tool, sources) for tool in tools], usage, fetcher, sources)


FAKE_PAGE = (
    "<html><head><title>VAT rates</title></head><body><h1>VAT rates</h1>"
    "<p>The standard rate of VAT is 20% on most goods and services.</p>"
    "<p>A reduced rate of 5% applies to some goods, such as home energy.</p>"
    "<p>Some goods are zero rated, which means VAT is charged at 0%.</p></body></html>"
)


def fake_web_research() -> WebResearch:
    """End-to-end tests: every search finds one gov.uk page, and every page is the same
    canned one. Nothing leaves the machine."""

    async def public(host: str, port: int) -> list[str]:
        return ["93.184.215.14"]

    def serve(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=FAKE_PAGE.encode(), headers={"content-type": "text/html"})

    return WebResearch(
        search=FakeSearch(default=[SearchHit("https://www.gov.uk/vat-rates", "VAT rates", "The standard rate is 20%")]),
        fetcher_factory=lambda: PageFetcher(
            resolver=public, transport=httpx.MockTransport(serve), min_interval=0, respect_robots=False
        ),
    )


def build_web_research(settings: Settings) -> WebResearch:
    provider = settings.search_provider
    if provider == "fake":
        return fake_web_research()
    if provider == "auto":
        provider = "tavily" if settings.tavily_api_key else "native"
    search: TavilySearch | None = None
    if provider == "tavily" and settings.tavily_api_key is not None:
        search = TavilySearch(settings.tavily_api_key.get_secret_value())
    return WebResearch(
        search=search,
        extractor=search if search is not None and settings.tavily_extract else None,
        max_searches=settings.research_max_searches,
        max_fetches=settings.research_max_fetches,
        daily_credits=settings.tavily_daily_credits,
    )


async def check_report(
    session: AsyncSession, workspace_id: uuid.UUID, run_id: uuid.UUID, items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Each report item's check (`dotrix_engine.web.verify`): its status and which quotes were
    found, against the run's sources and the pages they were read from."""
    rows = list(await session.scalars(select(ResearchSource).where(ResearchSource.run_id == run_id)))
    sources = {row.label: _source(row) for row in rows}
    read = {_hash(row.url): row.label for row in rows if row.kind == "page"}
    pages: dict[str, str] = {}
    if read:
        found = await session.execute(
            select(WebPage.url_key, WebPage.markdown).where(
                WebPage.workspace_id == workspace_id, WebPage.url_key.in_(list(read))
            )
        )
        pages = {read[key]: markdown for key, markdown in found}
    return [check_claim(item, sources, pages) for item in items]


async def delete_stale_pages(session: AsyncSession, before: datetime) -> int:
    result = await session.execute(delete(WebPage).where(WebPage.fetched_at < before))
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
