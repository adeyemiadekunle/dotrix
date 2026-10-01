"""A research note rendered from a report and its sources (docs/agents-v2.md §6.4)."""
from datetime import UTC, date, datetime

from pmagent_engine.web.note import note_path, render_note

ITEMS = [
    {"data": {"claim": "VAT is 20%", "sources": ["S1"], "quotes": [{"source": "S1", "text": "x"}],
              "confidence": "high", "affects": ["requirements/pricing.md"]},
     "state": "open", "check": {"status": "supported", "quotes": []}},
    {"data": {"claim": "VAT will rise", "sources": ["S2"], "confidence": "low"}, "state": "open",
     "check": {"status": "unsupported", "quotes": []}},
    {"data": {"claim": "Not useful", "sources": ["S1"]}, "state": "dismissed", "check": {"status": "weak"}},
]
SOURCES = [
    {"label": "S1", "url": "https://www.gov.uk/vat-rates", "title": "VAT [rates]", "host": "gov.uk", "tier": "primary",
     "kind": "page", "published": "2026-01-05T00:00:00Z", "fetched_at": datetime(2026, 10, 1, 9, tzinfo=UTC), "flagged": []},
    {"label": "S2", "url": "https://blog.example/x", "title": "Tips", "host": "blog.example", "tier": "other",
     "kind": "search", "published": None, "fetched_at": None, "flagged": ["asks to ignore instructions"]},
]


def test_the_note_has_the_fixed_sections() -> None:
    note = render_note(question='What\'s the UK "VAT" rate?', answer="### Summary\n\n---\n\nIt's 20%.\n\nMore detail.", items=ITEMS,
                       sources=SOURCES, researched=date(2026, 10, 1), run_id="run-1")
    assert note.startswith('---\nquestion: "What\'s the UK \\"VAT\\" rate?"\nresearched: 2026-10-01\nrun: run-1\n---\n')
    assert "## Short answer\n\nIt's 20%.\n" in note and "More detail" not in note
    assert "- VAT is 20% [S1] (high confidence, supported)" in note
    assert "## Assumptions" in note and "- VAT will rise [S2]" in note
    assert "Not useful" not in note  # dismissed
    assert "## What it affects\n\n- requirements/pricing.md" in note
    assert ("- **[S1]** [VAT (rates)](<https://www.gov.uk/vat-rates>): gov.uk · primary · published 2026-01-05 · "
            "read 2026-10-01") in note
    assert "- **[S2]** [Tips](<https://blog.example/x>): blog.example · other · seen in search results only" in note
    assert "## Pages that addressed AI agents" in note and "[S2] blog.example: asks to ignore instructions" in note


def test_paths_come_from_the_date_and_question() -> None:
    assert note_path("What's the UK VAT rate in 2026?", date(2026, 10, 1)) == "research/2026-10-01-uk-vat-rate-in-2026.md"
    assert note_path("???", date(2026, 10, 1)) == "research/2026-10-01-research.md"


def test_sources_only_seen_in_results_are_listed_apart() -> None:
    extra = {"label": "S3", "url": "https://example.org/a", "title": "Unused", "host": "example.org",
             "tier": "other", "kind": "search", "flagged": []}
    note = render_note(question="Q", answer="A", items=ITEMS[:1], sources=[*SOURCES[:1], extra],
                       researched=date(2026, 10, 1), run_id="r")
    assert "- **[S1]**" in note and "- **[S3]**" not in note
    assert "Also seen in search results: [S3] [Unused](<https://example.org/a>)" in note
