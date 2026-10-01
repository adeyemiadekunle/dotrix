"""Which web search agents get, from settings (docs/agents-v2.md §6.2)."""
import pytest

from pmagent_backend.core.settings import Settings
from pmagent_backend.modules.research.service import build_web_research


def settings(**values: object) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://localhost/unused",
        jwt_secret="test-only-jwt-secret-not-used-anywhere-else",  # type: ignore[arg-type]
        **{"tavily_api_key": None, **values},  # type: ignore[arg-type]
    )


def test_without_a_key_the_models_own_search_is_used() -> None:
    web = build_web_research(settings())
    assert web.search is None and web.extractor is None  # agents still read pages


def test_with_a_key_tavily_searches_and_reads_what_we_cant() -> None:
    web = build_web_research(settings(tavily_api_key="tvly-test", research_max_searches=3))
    assert web.search is not None and web.search.name == "tavily"
    assert web.extractor is web.search and web.max_searches == 3 and web.daily_credits == 500
    assert build_web_research(settings(tavily_api_key="tvly-test", tavily_extract=False)).extractor is None


def test_native_keeps_the_models_search_even_with_a_key() -> None:
    assert build_web_research(settings(tavily_api_key="tvly-test", search_provider="native")).search is None


def test_tavily_needs_its_key() -> None:
    with pytest.raises(ValueError, match="needs PMAGENT_TAVILY_API_KEY"):
        settings(search_provider="tavily")
