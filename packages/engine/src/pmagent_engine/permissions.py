"""Per-agent folder permissions (PRD "Who can read and write what", FR-41).

Every agent can read everything. Writes are scoped by folder:

- WRITE:   create and edit (with approval)
- TIDY:    Documentation may fix structure, links, formatting; never meaning
- PROPOSE: draft the change in a reply; the owning agent writes it after approval
- READ:    no writes

The platform enforces this on every agent write; it is not just a prompt.
Issues and sprints are also governed by the issue API (which issue types each
agent may create); this table covers them as files.
"""
from __future__ import annotations

import enum
from fnmatch import fnmatchcase


class Access(enum.StrEnum):
    READ = "read"
    PROPOSE = "propose"
    TIDY = "tidy"
    WRITE = "write"


PM, PRODUCT, ARCH, RESEARCH, REVIEWER, DOCS, CODING = (
    "project-manager",
    "product",
    "architecture",
    "research",
    "reviewer",
    "documentation",
    "coding",
)

W, P, T = Access.WRITE, Access.PROPOSE, Access.TIDY

# (patterns, {agent: access}); first matching row wins; unlisted agents READ.
_RULES: list[tuple[tuple[str, ...], dict[str, Access]]] = [
    # People (Owner / Admin) edit agent rules; agents never do.
    (("agent-rules/*",), {}),
    (("project.md", "docs/*"), {DOCS: W}),
    (("vision.md",), {PRODUCT: W, DOCS: T}),
    (("roadmap.md", "current-state.md"), {PM: W, PRODUCT: P, DOCS: T}),
    (("requirements/*",), {PRODUCT: W, ARCH: P, DOCS: T}),
    (("architecture/*",), {ARCH: W, DOCS: T}),
    (("research/*",), {RESEARCH: W, DOCS: T}),
    (("reviews/*",), {REVIEWER: W, DOCS: T}),
    (("decisions/*",), {DOCS: W, PM: P, PRODUCT: P, ARCH: P, RESEARCH: P, REVIEWER: P}),
    (("progress/*",), {PM: W, DOCS: T}),
    (("issues/*", "sprints/*"), {PM: W}),
]


def access(agent: str, path: str) -> Access:
    """What `agent` may do to `path` (relative to `.pmagent/`)."""
    for patterns, grants in _RULES:
        if any(fnmatchcase(path, pattern) for pattern in patterns):
            return grants.get(agent, Access.READ)
    return Access.READ  # anything unlisted is read-only for agents


def can_write(agent: str, path: str) -> bool:
    """Whether the agent may write the file itself (WRITE, or TIDY for Documentation)."""
    return access(agent, path) in (Access.WRITE, Access.TIDY)
