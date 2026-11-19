"""Model-independent web research configuration."""
import pytest

from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.research.service import build_web_research


def settings(**values):
    return Settings(database_url="postgresql+asyncpg://localhost/unused", jwt_secret="test-only-jwt-secret-not-used-anywhere-else", **values)


def test_unconfigured_search_still_allows_page_reads():
    assert build_web_research(settings()).search is None


def test_searxng_is_selected_without_model_provider_support():
    web = build_web_research(settings(searxng_url="http://search:8080"))
    assert web.search.name == "searxng" and web.extractor is None
    assert build_web_research(settings(searxng_url="http://search:8080", search_provider="native")).search is None


def test_searxng_requires_a_service():
    with pytest.raises(ValueError, match="DOTRIX_SEARXNG_URL"):
        settings(search_provider="searxng")


def test_removed_provider_is_rejected():
    with pytest.raises(ValueError):
        settings(search_provider="tavily")
