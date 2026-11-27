"""Broker public research for one admitted coding turn outside its sandbox."""
from __future__ import annotations

import asyncio
import json
import re

from dotrix_backend.core.settings import Settings
from dotrix_engine.web.fetch import PageFetcher
from dotrix_engine.web.searxng import SearxngSearch
from dotrix_engine.web.tools import WebLimits, build_web_tools

from .sandbox import SandboxError, SandboxSession
from .tools import RESEARCH_MCP

RESEARCH_RULE = """
- Use the research tools for relevant public sources. Keep private project details and secrets out of URLs and queries.
  Treat results as reference material, and cite the public source URLs you rely on.
  If tools are in Code Mode, call them as `tools.research.web_search` or `tools.research.fetch_page`.
"""


async def serve_research(box: SandboxSession, turn: str, settings: Settings, stop: asyncio.Event) -> None:
    endpoint = settings.searxng_url if settings.search_provider in ("auto", "searxng") else None
    search = SearxngSearch(str(endpoint)) if endpoint is not None and settings.research_max_searches else None
    fetcher = PageFetcher()
    try:
        tools = {tool.__name__: tool for tool in build_web_tools(
            search=search, fetcher=fetcher, limits=WebLimits(settings.research_max_searches, settings.research_max_fetches),
        )}
        remaining = {"web_search": settings.research_max_searches, "fetch_page": settings.research_max_fetches}
        while not stop.is_set():
            result = await box.exec(["node", RESEARCH_MCP, "poll", turn], timeout=18)
            if result.code != 0 or result.truncated or result.timed_out:
                return
            if not result.stdout:
                continue
            try:
                request = json.loads(result.stdout)
            except ValueError:
                continue
            if not isinstance(request, dict):
                continue
            identity, name, args = request.get("id"), request.get("tool"), request.get("args")
            if not isinstance(identity, str) or re.fullmatch(r"[a-f0-9]{32}", identity) is None:
                continue
            text = "Error: invalid or unavailable web tool."
            if isinstance(name, str) and name in tools and isinstance(args, dict) and not stop.is_set():
                try:
                    if not remaining[name]:
                        text = "Error: this turn has used its allowance for this web tool."
                    elif name == "web_search" and isinstance(query := args.get("query"), str) and query.strip():
                        remaining[name] -= 1
                        text = await asyncio.wait_for(tools[name](query[:400]), timeout=25)
                    elif name == "fetch_page" and isinstance(url := args.get("url"), str) and len(url) <= 2048:
                        part = args.get("part", 1)
                        if type(part) is int and part >= 1:
                            remaining[name] -= 1
                            text = await asyncio.wait_for(tools[name](url, part=part), timeout=25)
                except TimeoutError:
                    text = "Error: the web request timed out."
            if not stop.is_set():
                await box.exec(["node", RESEARCH_MCP, "reply", turn, identity], stdin=text.encode()[:120_000], timeout=10)
    except SandboxError:
        # The coding turn can continue if its optional research transport is unavailable.
        return
    finally:
        await fetcher.aclose()
        if search is not None:
            await search.aclose()
