"""How much a source can be trusted, from its address alone (docs/agents-v2.md §6.2).

`primary`: governments, legislation, regulators, standards bodies, international
organisations. `reputable`: established press, journals, preprint servers, and
universities. `other`: everything else (vendors' blogs, forums, personal sites).
Deterministic, so a report's tiers don't depend on the model.
"""
from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

Tier = Literal["primary", "reputable", "other"]

_PRIMARY_DOMAINS = frozenset({
    "europa.eu", "w3.org", "whatwg.org", "ietf.org", "rfc-editor.org", "iso.org", "iec.ch",
    "itu.int", "ecma-international.org", "unicode.org", "nist.gov", "oecd.org", "un.org",
    "worldbank.org", "imf.org", "bis.org", "fatf-gafi.org", "pcisecuritystandards.org",
    "cve.org", "nvd.nist.gov", "legislation.gov.uk", "ico.org.uk", "fca.org.uk",
})
# Second-level labels that mark a government under a country code (gov.uk, gov.ng, gouv.fr).
_GOVERNMENT_LABELS = frozenset({"gov", "gouv", "gob", "govt", "go", "gv", "admin", "bund"})
_PRIMARY_SUFFIXES = (".gov", ".mil", ".int")

_REPUTABLE_DOMAINS = frozenset({
    "reuters.com", "apnews.com", "bbc.co.uk", "bbc.com", "ft.com", "economist.com",
    "nytimes.com", "wsj.com", "bloomberg.com", "theguardian.com", "washingtonpost.com",
    "nature.com", "science.org", "sciencedirect.com", "springer.com", "wiley.com", "acm.org",
    "ieee.org", "arxiv.org", "nber.org", "techcrunch.com", "theverge.com", "arstechnica.com",
    "wired.com", "lwn.net",
})


def host_of(url: str) -> str:
    """The page's host without `www.`, lower case."""
    host = (urlsplit(url).hostname or "").rstrip(".").lower()
    return host.removeprefix("www.")


def _within(host: str, domains: frozenset[str]) -> bool:
    labels = host.split(".")
    return any(".".join(labels[i:]) in domains for i in range(len(labels)))


def tier(url: str) -> Tier:
    host = host_of(url)
    if not host:
        return "other"
    labels = host.split(".")
    if _within(host, _PRIMARY_DOMAINS) or host.endswith(_PRIMARY_SUFFIXES):
        return "primary"
    if len(labels) >= 2 and labels[-1].isalpha() and len(labels[-1]) == 2 and labels[-2] in _GOVERNMENT_LABELS:
        return "primary"
    if _within(host, _REPUTABLE_DOMAINS) or host.endswith(".edu") or (len(labels) >= 3 and labels[-2] == "ac"):
        return "reputable"
    return "other"
