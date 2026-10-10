"""The six built-in agents as contracts: the defaults every workspace starts from.

Their instructions, tools, folder access, and issue types are what the team has always had
(the folder matrix and issue rules come from `permissions`). Each follows its default pipeline
(`pipelines.DEFAULTS`) and returns that pipeline's result. Owners can edit them per workspace or project; "Reset to
default" goes back to these.
"""
from __future__ import annotations

from .contracts import PM_HANDLE, AgentSpec
from .permissions import (
    _RULES,
    ARCH,
    DOCS,
    ISSUE_CREATE_TYPES,
    PM,
    PRODUCT,
    RESEARCH,
    REVIEWER,
    Access,
)
from .pipelines import DEFAULTS as DEFAULT_PIPELINES
from .pipelines import PIPELINES

SPECIALISTS = (PRODUCT, ARCH, RESEARCH, REVIEWER, DOCS)

PM_INSTRUCTIONS = """Keep /dotrix/ (project.md, requirements/, architecture/, decisions/,
research/, progress/, docs/) as the single source of truth. Ingested
reference docs live under /dotrix/docs/normalized/ as markdown regardless
of their original format. Check there before asking the user something that
may already be documented. You do not write application code, and neither
do your subagents."""

_SPECIALIST_TEXT: dict[str, tuple[str, str, str]] = {
    # handle: (name, description, instructions)
    PRODUCT: (
        "Lyra",
        "Owns product thinking: features, user stories, business rules, acceptance criteria.",
        "Given a feature request, work through: why it's needed, who "
        "uses it, user stories, business rules, edge cases, acceptance "
        "criteria, and dependencies on other parts of the system. "
        "Write/update files under /dotrix/requirements/ via write_file. "
        "When asked to break a feature into tasks, use list_tasks to avoid "
        "duplicates, then propose them (title, description with acceptance "
        "criteria, priority, dependencies) in your reply. The PM creates them. "
        "Never write application code.",
    ),
    ARCH: (
        "Orion",
        "Tracks system architecture and the ripple effects of proposed changes.",
        "Maintain files under /dotrix/architecture/. When asked about a "
        "proposed change, name every existing module/entity it touches. "
        "Never write application code.",
    ),
    RESEARCH: (
        "Vega",
        "Runs external research (regulations, APIs, competitors, market changes).",
        "Investigate using web search. Clearly separate verified facts "
        "(with sources) from assumptions. Write findings under /dotrix/research/.",
    ),
    REVIEWER: (
        "Juno",
        "Reviews what has been built against stated requirements, including "
        "tasks in 'review' status handed back by coding agents. Read-only.",
        "Read /dotrix/requirements/ and /dotrix/architecture/ (and the "
        "actual repo, if you're given a way to see it) and produce a "
        "requirement-by-requirement status table (done / partial / "
        "missing) with what's missing and why. For a task in 'review', "
        "check the coding agent's final log note against the task's "
        "acceptance criteria and recommend: close, or send back with "
        "specific changes. You cannot write anything; report findings "
        "in your reply.",
    ),
    DOCS: (
        "Echo",
        "Keeps /dotrix/ organized; writes the decision log.",
        "Keep /dotrix/ tidy across project.md, requirements/, "
        "architecture/, decisions/, research/, progress/. When a "
        "decision is made, write a new /dotrix/decisions/ADR-NNN.md "
        "with: Decision, Reason, Date, Affected modules, Status. Never "
        "edit /dotrix/tasks/ files directly.",
    ),
}

# The tools each built-in has always had.
_READ = ["knowledge.read", "knowledge.search", "code.read", "graph.read"]
_TOOLS: dict[str, list[str]] = {
    PM: [*_READ, "knowledge.write", "board.read", "issues.create", "issues.update", "issues.comment",
         "graph.link", "web.search", "delegate"],
    PRODUCT: [*_READ, "knowledge.write", "board.read", "issues.create", "issues.comment", "graph.link", "delegate"],
    ARCH: [*_READ, "knowledge.write", "board.read", "issues.create", "issues.comment", "graph.link", "delegate"],
    # Research opens spikes (its rules say so); it had no board tools before contracts.
    RESEARCH: [*_READ, "knowledge.write", "board.read", "issues.create", "graph.link", "web.search", "delegate"],
    REVIEWER: [*_READ, "board.read", "issues.create", "issues.comment", "delegate"],
    DOCS: [*_READ, "knowledge.write", "board.read", "issues.comment", "graph.link", "delegate"],
}


def _access(role: str) -> dict[str, Access]:
    """The folder matrix's column for `role`, as the contract's access patterns (the matrix's
    rows don't overlap, so their order doesn't matter)."""
    grants: dict[str, Access] = {}
    for patterns, row in _RULES:
        if role in row:
            for pattern in patterns:
                grants[pattern] = row[role]
    return grants


def _issue_types(role: str, tools: list[str]) -> list[str]:
    if "issues.create" not in tools:
        return []
    return [t for t in ("epic", "story", "task", "bug", "spike", "sub-task") if t in ISSUE_CREATE_TYPES.get(role, ())]


# What each built-in does, said after its name in its prompt ("You are Vega, the research
# agent for Kunemi"); a contract based on a built-in keeps its role.
ROLES = {
    PM_HANDLE: "the project manager",
    PRODUCT: "the product agent",
    ARCH: "the architecture agent",
    RESEARCH: "the research agent",
    REVIEWER: "the reviewer agent",
    DOCS: "the documentation agent",
}


def introduce(spec: AgentSpec, project_name: str) -> str:
    """The first line of an agent's prompt: its name, what it does, and the project."""
    role = ROLES.get(spec.base or spec.handle)
    return f"You are {spec.name}, {role}, for {project_name}." if role else f"You are {spec.name}, an agent for {project_name}."


def builtin_specs() -> list[AgentSpec]:
    """Nova (the project manager) first, then the five specialists."""
    pm = AgentSpec(
        handle=PM_HANDLE,
        name="Nova",
        description="Coordinates the specialists and keeps the board and plan current.",
        base=PM_HANDLE,
        instructions=PM_INSTRUCTIONS,
        tools=_TOOLS[PM],
        access=_access(PM),
        issue_types=_issue_types(PM, _TOOLS[PM]),
        can_call=["*"],
        pipeline=DEFAULT_PIPELINES[PM],
    )
    specialists = [
        AgentSpec(
            handle=role,
            name=name,
            description=description,
            base=role,
            instructions=instructions,
            tools=_TOOLS[role],
            access=_access(role),
            issue_types=_issue_types(role, _TOOLS[role]),
            can_call=[other for other in SPECIALISTS if other != role],
            pipeline=DEFAULT_PIPELINES[role],
            output=PIPELINES[DEFAULT_PIPELINES[role]].output,
        )
        for role, (name, description, instructions) in _SPECIALIST_TEXT.items()
    ]
    return [pm, *specialists]


def builtin(handle: str) -> AgentSpec | None:
    return next((spec for spec in builtin_specs() if spec.handle == handle), None)


BUILTIN_HANDLES = (PM_HANDLE, *SPECIALISTS)
