"""The agents' web: search through a provider (Tavily), safe page reads, sources with ids,
and web text kept as data (docs/agents-v2.md §6)."""
from .fetch import BlockedAddress, FetchError, Page, PageFetcher, PublicOnlyTransport, is_public
from .search import FakeSearch, SearchHit, SearchProvider, SearchUnavailable, TavilySearch
from .tiers import tier
from .tools import (
    WEB_GUIDE,
    MemoryPageCache,
    PageCache,
    Source,
    SourceLog,
    WebLimits,
    WebUsage,
    build_web_tools,
)
from .untrusted import suspicious, wrap

__all__ = [
    "WEB_GUIDE", "BlockedAddress", "FakeSearch", "FetchError", "MemoryPageCache", "Page",
    "PageCache", "PageFetcher", "PublicOnlyTransport", "SearchHit", "SearchProvider",
    "SearchUnavailable", "Source", "SourceLog", "TavilySearch", "WebLimits", "WebUsage",
    "build_web_tools", "is_public", "suspicious", "tier", "wrap",
]
