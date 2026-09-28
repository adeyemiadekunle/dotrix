"""What a knowledge document is about, without reading it: a title, a one-line summary, and
its heading outline, taken from the Markdown itself (no model call).

The platform stores these with every document and lists them in the context pack each agent
run starts with, so agents can decide what to open instead of opening everything.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

MAX_SUMMARY = 240
MAX_OUTLINE = 25

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_MARKS = re.compile(r"(\*\*|__|\*|_|`)")
_LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(\[[ xX]\]\s+)?")


@dataclass(frozen=True)
class Description:
    title: str
    summary: str
    outline: list[str] = field(default_factory=list)  # "## Goals", "### Non-goals", ...


def _plain(text: str) -> str:
    text = _LINK.sub(r"\1", text)
    text = _MARKS.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:-")
    return f"{cut}…"


def _title_from_path(path: str) -> str:
    stem = PurePosixPath(path).stem.replace("-", " ").replace("_", " ").strip()
    return stem[:1].upper() + stem[1:] if stem else path


def describe(path: str, content: str) -> Description:
    """The title (the first H1, else the file name), the first paragraph of prose as the
    summary (skipping headings, code, tables, and quoted notes when there's anything else),
    and the section headings below the title."""
    text = _FRONT_MATTER.sub("", content.replace("\r\n", "\n"))
    title: str | None = None
    outline: list[str] = []
    paragraphs: list[str] = []
    quoted: list[str] = []
    current: list[str] = []
    in_code = False

    def flush() -> None:
        if current:
            paragraphs.append(" ".join(current))
            current.clear()

    for raw in text.split("\n"):
        line = raw.rstrip()
        if line.lstrip().startswith(("```", "~~~")):
            in_code = not in_code
            flush()
            continue
        if in_code:
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            level, words = len(heading.group(1)), _plain(heading.group(2))
            if level == 1 and title is None:
                title = words
            elif words and len(outline) < MAX_OUTLINE:
                outline.append(f"{'#' * level} {words}")
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("|") or set(stripped) <= set("-=*_ "):
            flush()
            continue
        if stripped.startswith(">"):
            flush()
            quoted.append(_plain(stripped.lstrip("> ")))
            continue
        current.append(_plain(_LIST_MARKER.sub("", stripped)))
    flush()

    prose = next((p for p in paragraphs if p), None) or next((q for q in quoted if q), "")
    return Description(
        title=_shorten(title or _title_from_path(path), 200),
        summary=_shorten(prose, MAX_SUMMARY) if prose else "(empty)",
        outline=outline,
    )
