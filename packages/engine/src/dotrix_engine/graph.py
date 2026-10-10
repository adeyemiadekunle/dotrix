"""Finding the links in a project's text, for the project graph (agents v2 step 3).

Pure functions: the platform stores the graph and walks it. What's found here is
deterministic, so the same text always gives the same links:

- issue keys ("KUN-42") anywhere in a document or an issue;
- documents by path ("requirements/auth.md", "/dotrix/decisions/ADR-003.md", a relative
  link to one that exists, or a folder path to one that doesn't yet) or ADRs by name ("ADR-3");
- an ADR's "Supersedes:" line, and its "Affected modules:" (a line or a section's bullets).

From an issue, a requirement it names is what it `implements` and a decision it names is what
it was `decided_by`; every other reference `mentions`.
"""
from __future__ import annotations

import posixpath
import re
from collections.abc import Collection
from dataclasses import dataclass

MENTIONS = "mentions"
IMPLEMENTS = "implements"
DECIDED_BY = "decided_by"
SUPERSEDES = "supersedes"
AFFECTS = "affects"
MODULE_PREFIX = "module:"

MAX_MODULES = 20
MAX_REFERENCES = 200

_PATH = re.compile(r"(?<![\w/.-])(?:\.{1,2}/|/)*[\w][\w./-]*\.md\b")
_ADR = re.compile(r"\bADR-0*(\d{1,5})\b", re.IGNORECASE)
_ADR_FILE = re.compile(r"(?:^|/)adr-0*(\d{1,5})(?!\d)", re.IGNORECASE)
_SUPERSEDES = re.compile(r"^\W*supersedes\W*:", re.IGNORECASE)
_MODULES_LINE = re.compile(r"^\W*affected modules?\W*:\s*(.*)$", re.IGNORECASE)
_MODULES_HEADING = re.compile(r"^#{1,6}\s+affected modules?\s*$", re.IGNORECASE)
_HEADING = re.compile(r"^#{1,6}\s")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_NO_MODULE = {"", "-", "…", "...", "none", "n/a", "na", "tbd"}


@dataclass(frozen=True)
class Reference:
    target: str  # an issue key, a document path, or "module:<name>"
    kind: str
    title: str | None = None  # a module's name as written


def folder(path: str) -> str:
    return path.split("/", 1)[0] if "/" in path else ""


def module_ref(name: str) -> str:
    return MODULE_PREFIX + " ".join(name.lower().split())


def _module_names(value: str) -> list[str]:
    names = []
    for part in re.split(r"[,;]|\band\b", value):
        name = part.strip().strip("`*_.").strip()
        if name.lower() not in _NO_MODULE and len(name) <= 60:
            names.append(name)
    return names


class _Paths:
    """The project's document paths, to resolve what text names."""

    def __init__(self, paths: Collection[str]) -> None:
        self.paths = set(paths)
        self.adrs: dict[int, str] = {}
        for path in sorted(self.paths):
            match = _ADR_FILE.search(path)
            if path.startswith("decisions/") and match:
                self.adrs.setdefault(int(match.group(1)), path)

    def resolve(self, token: str, source: str) -> str | None:
        token = token.strip()
        for prefix in ("/dotrix/", "dotrix/", "/"):
            if token.startswith(prefix) and token[len(prefix):] in self.paths:
                return token[len(prefix):]
        if token in self.paths:
            return token
        if not token.startswith("/"):
            joined = posixpath.normpath(posixpath.join(posixpath.dirname(source), token))
            if joined in self.paths:
                return joined
        # A project path that doesn't exist yet ("requirements/sso.md"): kept, so the link
        # appears once the document does.
        if "/" in token and not token.startswith((".", "/")) and ".." not in token:
            return token
        return None


def find_references(
    text: str, *, source: str, project_key: str, paths: Collection[str], is_issue: bool = False
) -> list[Reference]:
    """What `text` (a document's, or an issue's description and links) refers to.

    `source` is the document's path or the issue's key; `paths` are the project's documents."""
    known = _Paths(paths)
    key_pattern = re.compile(rf"\b{re.escape(project_key)}-(\d+)\b")
    found: dict[tuple[str, str], Reference] = {}

    def add(target: str, kind: str, title: str | None = None) -> None:
        if target != source and len(found) < MAX_REFERENCES:
            found.setdefault((target, kind), Reference(target, kind, title))

    def document_kind(path: str) -> str:
        if not is_issue:
            return MENTIONS
        return {"requirements": IMPLEMENTS, "decisions": DECIDED_BY}.get(folder(path), MENTIONS)

    modules = 0
    in_modules_section = False
    for line in text.splitlines():
        if _HEADING.match(line):
            in_modules_section = bool(_MODULES_HEADING.match(line.strip()))
            continue
        supersedes = bool(_SUPERSEDES.match(line))
        names: list[str] = []
        if (match := _MODULES_LINE.match(line)) is not None:
            names = _module_names(match.group(1))
        elif in_modules_section and (bullet := _BULLET.match(line)) is not None:
            names = _module_names(bullet.group(1))
        for name in names:
            if modules < MAX_MODULES:
                add(module_ref(name), AFFECTS, name)
                modules += 1
        for match in key_pattern.finditer(line):
            add(f"{project_key}-{int(match.group(1))}", MENTIONS)
        for match in _PATH.finditer(line):
            if (path := known.resolve(match.group(0), source)) is not None:
                add(path, SUPERSEDES if supersedes else document_kind(path))
        for match in _ADR.finditer(line):
            if (path := known.adrs.get(int(match.group(1)))) is not None:
                add(path, SUPERSEDES if supersedes else document_kind(path))

    # A target named in a stronger way isn't also "mentioned".
    strong = {target for target, kind in found if kind != MENTIONS}
    return [ref for (target, kind), ref in found.items() if kind != MENTIONS or target not in strong]
