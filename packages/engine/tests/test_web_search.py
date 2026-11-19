"""Deterministic test search provider."""
from dotrix_engine.web.search import FakeSearch, SearchHit


async def test_fake_search_matches_by_phrase_and_records_queries() -> None:
    hit = SearchHit("https://example.com", "Example", "text")
    fake = FakeSearch({"vat": [hit]})
    assert await fake.search("UK VAT rate", recency_days=7) == [hit]
    assert await fake.search("something else") == []
    assert fake.queries[0]["recency_days"] == 7
