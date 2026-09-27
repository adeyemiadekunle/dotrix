"""Per-agent folder permissions (PRD "Who can read and write what", FR-41).

Every agent can read everything. Writes are scoped by folder:

- WRITE:   create and edit (with approval)
- TIDY:    Documentation may fix structure, links, formatting; never meaning
- PROPOSE: draft the change in a reply; the owning agent writes it after approval
- READ:    no writes

The platform enforces this on every agent write; it is not just a prompt.
Issues are governed by `can_create_issue` / `can_edit_issues` below (the PRD's
"issues/, sprints/" row); the folder table covers them as files.
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


# PRD "issues/, sprints/" row: the PM writes the board; specialists may only open
# new issues of their own kind (with approval), never edit others' issues.
ISSUE_TYPES = ("epic", "story", "task", "bug", "spike", "sub-task")
ISSUE_CREATE_TYPES: dict[str, frozenset[str]] = {
    PM: frozenset(ISSUE_TYPES),
    PRODUCT: frozenset({"epic", "story"}),
    ARCH: frozenset({"task"}),
    RESEARCH: frozenset({"spike"}),
    REVIEWER: frozenset({"bug"}),
}


def can_create_issue(agent: str, issue_type: str) -> bool:
    return issue_type in ISSUE_CREATE_TYPES.get(agent, frozenset())


def can_edit_issues(agent: str) -> bool:
    """Change fields and status of existing issues (including closing them, with approval)."""
    return agent == PM
