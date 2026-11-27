"""Read-only public research for Kai over the native runner's fixed relay."""
from __future__ import annotations

import asyncio
import json

from dotrix_engine.web.fetch import PageFetcher
from dotrix_engine.web.searxng import SearxngSearch
from dotrix_engine.web.tools import WebLimits, build_web_tools


class ResearchMcp:
    def __init__(self, endpoint: str | None) -> None:
        self.search = SearxngSearch(endpoint) if endpoint else None
        self.fetcher = PageFetcher()
        self.tools = {tool.__name__: tool for tool in build_web_tools(search=self.search, fetcher=self.fetcher)}
        self.lock = asyncio.Lock()
        limits = WebLimits()
        self.remaining = {"web_search": limits.max_searches, "fetch_page": limits.max_fetches}

    async def aclose(self) -> None:
        await self.fetcher.aclose()
        if self.search is not None:
            await self.search.aclose()

    async def request(self, method: str, body: bytes) -> tuple[int, dict | None]:
        if method != "POST":
            return 405, None
        if len(body) > 8192:
            return 413, None
        try:
            message = json.loads(body)
        except ValueError:
            return 400, None
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return 400, None
        if "id" not in message:
            return 202, None
        response = {"jsonrpc": "2.0", "id": message["id"]}
        match message.get("method"):
            case "initialize":
                result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "dotrix-research", "version": "1"}}
            case "ping":
                result = {}
            case "tools/list":
                result = {"tools": self.catalog()}
            case "tools/call":
                text = await self.call(message.get("params"))
                result = {"content": [{"type": "text", "text": text}], "isError": text.startswith("Error:")}
            case _:
                return 200, {**response, "error": {"code": -32601, "message": "Method not found"}}
        return 200, {**response, "result": result}

    def catalog(self) -> list[dict]:
        tools = [{"name": "fetch_page", "description": "Read a public URL as untrusted reference material.",
                  "inputSchema": {"type": "object", "properties": {"url": {"type": "string", "maxLength": 2048},
                                  "part": {"type": "integer", "minimum": 1}}, "required": ["url"]}}]
        if self.search is not None:
            tools.append({"name": "web_search", "description": "Find public sources using a query without private details.",
                          "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "maxLength": 400}},
                                          "required": ["query"]}})
        return tools

    async def call(self, params: object) -> str:
        if not isinstance(params, dict) or not isinstance(args := params.get("arguments"), dict):
            return "Error: invalid web tool arguments."
        name = params.get("name")
        if not isinstance(name, str) or name not in self.tools:
            return "Error: this web tool is unavailable."
        if name == "web_search":
            value = args.get("query")
            if not isinstance(value, str) or not value.strip() or len(value) > 400:
                return "Error: supply a query of 1 to 400 characters."
            kwargs = {}
        else:
            value, part = args.get("url"), args.get("part", 1)
            if not isinstance(value, str) or not 1 <= len(value) <= 2048 or type(part) is not int or part < 1:
                return "Error: supply a public URL and a positive part number."
            kwargs = {"part": part}
        async with self.lock:
            if not self.remaining[name]:
                return "Error: this turn has used its allowance for this web tool."
            self.remaining[name] -= 1
            try:
                return await asyncio.wait_for(self.tools[name](value, **kwargs), timeout=25)
            except TimeoutError:
                return "Error: the web request timed out."
