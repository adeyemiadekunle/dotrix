"""Checking a report's claims against what was read (docs/agents-v2.md §6.3), in code.

Each claim quotes its sources. A quote counts when it occurs in the stored page (or, failing
that, the search snippet), after normalising case, whitespace, punctuation, and Markdown link
targets, or differs only the way text extraction does (a word split or joined, a word's
ending); a changed word or number never matches. Then:

- no quote found: `unsupported` (shown as an assumption, not a finding)
- found only in snippets, or only in `other`-tier sources: `weak`
- found in a page read in full from a `primary` or `reputable` source: `supported`

The agent's own judgement can lower a status (a `low` confidence makes it at most `weak`),
never raise it. No model call.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from difflib import SequenceMatcher
from typing import Any, Literal

from .tools import Source

Status = Literal["supported", "weak", "unsupported"]
MIN_QUOTE_WORDS = 3

_LINK_TARGET = re.compile(r"\]\([^)]*\)")
_NOT_WORD = re.compile(r"[^\w]+")


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", _LINK_TARGET.sub("] ", text)).lower()
    return " ".join(_NOT_WORD.sub(" ", text).split())


def _tolerable(page: str, quoted: str) -> bool:
    """Differences extraction makes, not ones that change what's said: a word split or joined
    ("e mail" / "email"), or a word's ending ("service" / "services")."""
    if page == quoted:
        return True
    return bool(page and quoted) and (page.startswith(quoted) or quoted.startswith(page)) and (
        abs(len(page) - len(quoted)) <= 2
    )


def quote_in(quote: str, text: str) -> bool:
    """Whether `quote` occurs in `text` word for word after normalising, or with only the small
    differences extraction makes. A changed word or number never matches."""
    q, t = normalise(quote).split(), normalise(text).split()
    if len(q) < MIN_QUOTE_WORDS or not t:
        return False
    if f" {' '.join(q)} " in f" {' '.join(t)} ":
        return True
    i, j, size = SequenceMatcher(None, t, q, autojunk=False).find_longest_match(0, len(t), 0, len(q))
    if size == 0:
        return False
    window = t[max(0, i - j): i - j + len(q) + 3]
    for tag, a1, a2, b1, b2 in SequenceMatcher(None, window, q, autojunk=False).get_opcodes():
        if tag == "equal" or (tag == "delete" and b1 in (0, len(q))):
            continue  # the same, or page words before or after the quote
        quoted, page = "".join(q[b1:b2]), window[a1:a2]
        # At the quote's ends the page may go on: compare with the page words next to the quote.
        options = {"".join(page)}
        if b2 == len(q):
            options |= {"".join(page[:k]) for k in range(1, len(page))}
        if b1 == 0:
            options |= {"".join(page[k:]) for k in range(1, len(page))}
        if not any(_tolerable(option, quoted) for option in options):
            return False
    return True


def _source(ref: str, sources: Mapping[str, Source]) -> Source | None:
    ref = ref.strip().strip("[]")
    if ref in sources:
        return sources[ref]
    return next((s for s in sources.values() if s.url == ref), None)


def check_claim(item: Mapping[str, Any], sources: Mapping[str, Source], pages: Mapping[str, str]) -> dict[str, Any]:
    """{"status", "quotes": [{"source", "found": "page" | "snippet" | None}]} for one report
    item. `sources` by id; `pages` holds the stored text of the sources read in full, by id."""
    checks: list[dict[str, Any]] = []
    strong = found_any = False
    for quote in item.get("quotes") or []:
        ref, text = str(quote.get("source", "")), str(quote.get("text", ""))
        source = _source(ref, sources)
        found = None
        if source is not None:
            if (page := pages.get(source.label)) and quote_in(text, page):
                found = "page"
            elif source.snippet and quote_in(text, source.snippet):
                found = "snippet"
        checks.append({"source": source.label if source else ref, "found": found})
        found_any = found_any or found is not None
        strong = strong or (found == "page" and source is not None and source.tier != "other")
    status: Status = "supported" if strong else "weak" if found_any else "unsupported"
    if status == "supported" and item.get("confidence") == "low":
        status = "weak"
    return {"status": status, "quotes": checks}
