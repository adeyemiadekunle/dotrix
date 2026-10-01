"""A report's claims checked against what was read, in code (docs/agents-v2.md §6.3)."""
import pytest

from pmagent_engine.web import Source, check_claim, quote_in

PAGE = (
    "# VAT rates\n\nThe **standard rate** of VAT is 20% on most goods and services. "
    "See [the reduced rate](https://www.gov.uk/reduced) for energy.\n"
)
SOURCES = {
    "S1": Source("S1", "https://www.gov.uk/vat", tier="primary", kind="page"),
    "S2": Source("S2", "https://blog.example/vat", tier="other", kind="page"),
    "S3": Source("S3", "https://www.reuters.com/vat", tier="reputable", snippet="VAT stays at 20% next year, officials said"),
}
PAGES = {"S1": PAGE, "S2": PAGE}


@pytest.mark.parametrize("quote", [
    "The standard rate of VAT is 20% on most goods and services.",
    "the standard rate of vat is 20 on most goods",  # case, punctuation, Markdown emphasis
    "See the reduced rate for energy",  # link targets ignored
    "The standard rate of VAT is 20% on most goods and service",  # a word's ending
    "The standard rate of VAT is 20% on most goodsand services",  # words run together
])
def test_quotes_found(quote: str) -> None:
    assert quote_in(quote, PAGE)


@pytest.mark.parametrize("quote", [
    "The standard rate of VAT is 25% on all goods and services.",
    "Businesses must register above £90,000.",
    "The standard rate of VAT is 20% on all goods and services.",
    "The reduced rate of VAT is 20% on most goods and services.",
    "VAT is",  # too short to show anything
    "",
])
def test_quotes_not_found(quote: str) -> None:
    assert not quote_in(quote, PAGE)


def claim(*quotes: tuple[str, str], confidence: str = "medium") -> dict:
    return {"claim": "VAT is 20%", "confidence": confidence,
            "quotes": [{"source": s, "text": t} for s, t in quotes]}


QUOTE = "The standard rate of VAT is 20% on most goods and services."


def test_found_in_a_primary_page_is_supported() -> None:
    result = check_claim(claim(("S1", QUOTE)), SOURCES, PAGES)
    assert result == {"status": "supported", "quotes": [{"source": "S1", "found": "page"}]}


def test_a_quote_not_in_the_page_is_unsupported() -> None:
    result = check_claim(claim(("S1", "VAT was abolished in 2025 for all businesses.")), SOURCES, PAGES)
    assert result["status"] == "unsupported" and result["quotes"][0]["found"] is None


def test_no_quotes_or_unknown_sources_are_unsupported() -> None:
    assert check_claim(claim(), SOURCES, PAGES)["status"] == "unsupported"
    assert check_claim(claim(("S9", QUOTE)), SOURCES, PAGES) == {
        "status": "unsupported", "quotes": [{"source": "S9", "found": None}]}


def test_other_tier_or_snippet_only_is_weak() -> None:
    assert check_claim(claim(("S2", QUOTE)), SOURCES, PAGES)["status"] == "weak"
    snippet = check_claim(claim(("[S3]", "VAT stays at 20% next year")), SOURCES, PAGES)
    assert snippet == {"status": "weak", "quotes": [{"source": "S3", "found": "snippet"}]}


def test_sources_by_url_and_low_confidence() -> None:
    assert check_claim(claim(("https://www.gov.uk/vat", QUOTE)), SOURCES, PAGES)["status"] == "supported"
    assert check_claim(claim(("S1", QUOTE), confidence="low"), SOURCES, PAGES)["status"] == "weak"
