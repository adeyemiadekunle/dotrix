"""A research note from a report (docs/agents-v2.md §6.4): the fixed sections, rendered from
the run's result and its sources, so the sources list is always exact.

Findings are the claims backed by what was read (`supported` or `weak`); claims no quote was
found for go under "Assumptions". Dismissed items are left out.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from typing import Any

_WORD = re.compile(r"[a-z0-9]+")


def note_path(question: str, on: date) -> str:
    """`research/2026-10-01-uk-vat-rate.md`: the date and the question's first words."""
    words = [w for w in _WORD.findall(question.lower()) if w not in {"what", "whats", "s", "the", "a", "an", "is", "are"}]
    slug = "-".join(words[:6])[:60].strip("-") or "research"
    return f"research/{on.isoformat()}-{slug}.md"


def _first_paragraph(text: str) -> str:
    """The answer's first paragraph, past any headings and rules ("### Summary", "---")."""
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [line for line in block.strip().splitlines()
                 if line.strip() and not re.fullmatch(r"\s*(#{1,6}\s.*|[-*_]{3,})\s*", line)]
        if lines:
            return "\n".join(lines).strip()
    return ""


def _cites(data: Mapping[str, Any]) -> str:
    refs = [str(s).strip().strip("[]") for s in data.get("sources") or [] if str(s).strip()]
    refs += [str(q.get("source", "")).strip().strip("[]") for q in data.get("quotes") or [] if isinstance(q, Mapping)]
    unique = list(dict.fromkeys(r for r in refs if re.fullmatch(r"S\d+", r)))
    return " " + "".join(f"[{r}]" for r in unique) if unique else ""


def _day(value: Any) -> str:
    if isinstance(value, datetime | date):
        return value.isoformat()[:10]
    return str(value)[:10] if value else ""


def _link(source: Mapping[str, Any]) -> str:
    title = str(source.get("title") or source.get("url") or "").replace("[", "(").replace("]", ")")
    return f"[{title}](<{source.get('url', '')}>)"


def render_note(
    *,
    question: str,
    answer: str,
    items: Iterable[Mapping[str, Any]],
    sources: Iterable[Mapping[str, Any]],
    researched: date,
    run_id: str,
) -> str:
    """The note's Markdown. `items` are a report's stored items ({"data", "state", "check"});
    `sources` the run's sources (label, url, title, host, tier, kind, published, fetched_at,
    flagged)."""
    kept = [i for i in items if i.get("state") != "dismissed"]
    findings = [i for i in kept if (i.get("check") or {}).get("status") != "unsupported"]
    assumptions = [i for i in kept if (i.get("check") or {}).get("status") == "unsupported"]
    sources = list(sources)

    lines = [
        "---",
        f"question: {json.dumps(question.strip(), ensure_ascii=False)}",
        f"researched: {researched.isoformat()}",
        f"run: {run_id}",
        "---",
        "",
        f"# {question.strip().splitlines()[0] if question.strip() else 'Research'}",
        "",
        "## Short answer",
        "",
        _first_paragraph(answer) or "_No short answer was given._",
        "",
        "## Findings",
        "",
    ]
    for item in findings:
        data, check = item.get("data") or {}, item.get("check") or {}
        notes = [f"{data.get('confidence', 'medium')} confidence"]
        if check.get("status"):
            notes.append(str(check["status"]))
        lines.append(f"- {str(data.get('claim', '')).strip()}{_cites(data)} ({', '.join(notes)})")
    if not findings:
        lines.append("_None backed by the sources read._")
    if assumptions:
        lines += ["", "## Assumptions", "", "Claims no quote was found for in the pages read:", ""]
        lines += [f"- {str((i.get('data') or {}).get('claim', '')).strip()}{_cites(i.get('data') or {})}"
                  for i in assumptions]
    affects = list(dict.fromkeys(str(a) for i in kept for a in (i.get("data") or {}).get("affects") or []))
    if affects:
        lines += ["", "## What it affects", ""] + [f"- {a}" for a in affects]
    # The sources the note cites or that were read in full; the rest were only seen in results.
    cited = {r.strip("[]") for i in kept for r in _cites(i.get("data") or {}).replace("][", " ").strip(" []").split()}
    listed = [s for s in sources if s.get("label") in cited or s.get("kind") == "page"]
    others = [s for s in sources if s not in listed]
    lines += ["", "## Sources", ""]
    for source in listed:
        parts = [str(source.get("host") or ""), str(source.get("tier") or "other")]
        if source.get("published"):
            parts.append(f"published {_day(source['published'])}")
        parts.append(f"read {_day(source['fetched_at'])}" if source.get("kind") == "page" and source.get("fetched_at")
                     else "seen in search results only")
        lines.append(f"- **[{source.get('label')}]** {_link(source)}: {' · '.join(p for p in parts if p)}")
    if not listed:
        lines.append("_No web sources._")
    if others:
        lines += ["", "Also seen in search results: " + ", ".join(
            f"[{s.get('label')}] {_link(s)}" for s in others)]
    flagged = [s for s in sources if s.get("flagged")]
    if flagged:
        lines += ["", "## Pages that addressed AI agents", "",
                  "Their instructions were ignored; treat what they say with care.", ""]
        lines += [f"- [{s.get('label')}] {s.get('host')}: {', '.join(s['flagged'])}" for s in flagged]
    return "\n".join(lines).rstrip() + "\n"
