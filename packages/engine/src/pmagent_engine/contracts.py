"""Agent contracts: an agent as data (docs/agents-v2.md §4).

A contract (`AgentSpec`) says who an agent is and what it may do: its instructions, tools
(ids from `catalog`), folder access, the issue types it may open, who it may call, and how
much it may do without asking. The six built-in agents are contracts too (`builtins`), so a
workspace that customises nothing behaves as before.

Contracts are validated here, and `AgentPolicy` answers the permission questions the platform
asks on every agent write. Some rules hold whatever a contract says (§4.4): agents never write
`agent-rules/`, and anything a contract can't express stays `ask`.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from fnmatch import fnmatchcase
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .catalog import ACTIONS, CATALOG, TOOL_IDS, group
from .permissions import ISSUE_TYPES, Access

HANDLE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
PM_HANDLE = "project-manager"
# Handles no custom agent can take: the built-ins' (edit those instead) and chat's "auto".
RESERVED_HANDLES = frozenset({"auto", PM_HANDLE, "product", "architecture", "research", "reviewer",
                              "documentation", "coding"})
PEOPLE_ONLY = ("agent-rules/*",)  # no contract can make these writable (§4.4)
MAX_INSTRUCTIONS = 20_000

Autonomy = Literal["allow", "ask", "block"]


class AgentSpec(BaseModel):
    """One agent's contract. Everything but `handle`, `name`, and `instructions` has a default."""

    model_config = ConfigDict(extra="forbid")

    handle: str = Field(description="Lower-case id used in chat as @handle, e.g. security")
    name: str = Field(min_length=1, max_length=60, description="Shown in the app, e.g. Security reviewer")
    description: str = Field(default="", max_length=200, description="One line, shown in the chat's + menu")
    base: str | None = Field(default=None, description="The built-in it was cloned from, if any")
    instructions: str = Field(min_length=1, max_length=MAX_INSTRUCTIONS, description="Its role prompt (Markdown)")
    model: str | None = Field(default=None, max_length=100, description="provider:model; null uses the run's")
    budget_tokens: int | None = Field(default=None, ge=10_000, le=10_000_000)
    tools: list[str] = Field(default_factory=lambda: ["knowledge.read", "knowledge.search", "board.read"])
    access: dict[str, Access] = Field(
        default_factory=dict, description="Folder pattern (relative to .pmagent/) -> read, propose, tidy, or write"
    )
    issue_types: list[str] = Field(default_factory=list, description="Issue types it may open")
    can_call: list[str] = Field(default_factory=list, description="Handles it may hand work to; ['*'] for all")
    autonomy: dict[str, Autonomy] = Field(default_factory=dict, description="Action -> allow, ask, or block")
    output: str | None = None
    pipeline: str | None = None
    triggers: list[dict] = Field(default_factory=list)

    @field_validator("handle")
    @classmethod
    def _handle(cls, value: str) -> str:
        if not HANDLE.match(value) or value.endswith("-agent"):
            raise ValueError("Use 2-31 lower-case letters, digits, and dashes, starting with a letter")
        return value

    @field_validator("tools")
    @classmethod
    def _tools(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - set(TOOL_IDS))
        if unknown:
            raise ValueError(f"Unknown tools: {', '.join(unknown)}")
        return list(dict.fromkeys(value))

    @field_validator("access")
    @classmethod
    def _access(cls, value: dict[str, Access]) -> dict[str, Access]:
        for pattern, level in value.items():
            if not pattern or pattern.startswith("/") or ".." in pattern:
                raise ValueError(f"Folder patterns are relative to .pmagent/, e.g. research/*: {pattern!r}")
            if level is not Access.READ and any(fnmatchcase(pattern, p) or pattern.startswith("agent-rules")
                                                for p in PEOPLE_ONLY):
                raise ValueError("Agents can't be given write access to agent-rules/; people edit those")
        return value

    @field_validator("issue_types")
    @classmethod
    def _issue_types(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - set(ISSUE_TYPES))
        if unknown:
            raise ValueError(f"Unknown issue types: {', '.join(unknown)}")
        return list(dict.fromkeys(value))

    @field_validator("autonomy")
    @classmethod
    def _autonomy(cls, value: dict[str, Autonomy]) -> dict[str, Autonomy]:
        unknown = sorted(set(value) - set(ACTIONS))
        if unknown:
            raise ValueError(f"Unknown actions: {', '.join(unknown)}")
        return value

    @field_validator("output")
    @classmethod
    def _output(cls, value: str | None) -> str | None:
        from .outputs import SCHEMAS

        if value is not None and value not in SCHEMAS:
            raise ValueError(f"Unknown output: {value}; use one of {', '.join(SCHEMAS)}")
        return value

    @field_validator("pipeline")
    @classmethod
    def _pipeline(cls, value: str | None) -> str | None:
        from .outputs import PIPELINES

        if value is not None and value not in PIPELINES:
            raise ValueError(f"Unknown pipeline: {value}; use one of {', '.join(PIPELINES)}")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> AgentSpec:
        if self.issue_types and "issues.create" not in self.tools:
            raise ValueError("Issue types need the 'Open issues' tool (issues.create)")
        return self

    # -- what the contract means ------------------------------------------------------------

    @property
    def agent_name(self) -> str:
        """Its LangGraph name; `role_for_agent_name` maps it back to the handle."""
        return f"{self.handle}-agent"

    def has(self, tool: str) -> bool:
        return tool in self.tools

    def rule(self, action: str) -> Autonomy:
        """allow, ask, or block. Unlisted actions ask."""
        return self.autonomy.get(action, "ask")

    def can(self, tool: str) -> bool:
        """It has the tool and none of the tool's actions is blocked."""
        return self.has(tool) and not any(self.rule(a) == "block" for a in group(tool).actions)

    def allowed(self, action: str) -> bool:
        """It may take `action` without asking: an owner's standing rule."""
        return self.rule(action) == "allow"

    def allows(self) -> list[str]:
        """The actions it may take without asking, among the tools it has."""
        return [a for a in ACTIONS if self.allowed(a) and self.can(_TOOL_FOR_ACTION[a])]

    def asking(self, actions: Iterable[str]) -> AgentSpec:
        """This contract with `actions` turned from allow back to ask (a run that may not act
        unattended: paused, a briefing, an automation without the switch)."""
        drop = {a for a in actions if self.rule(a) == "allow"}
        if not drop:
            return self
        return self.model_copy(update={"autonomy": {a: ("ask" if a in drop else r) for a, r in self.autonomy.items()}})

    def folder_access(self, path: str) -> Access:
        """What this agent may do to `path` (relative to `.pmagent/`): the first matching pattern
        in its `access`, else read. People-only folders are always read, whatever it says."""
        if any(fnmatchcase(path, p) for p in PEOPLE_ONLY):
            return Access.READ
        if not self.can("knowledge.write"):
            return min(self._matching(path), Access.PROPOSE, key=_RANK.index)
        return self._matching(path)

    def _matching(self, path: str) -> Access:
        for pattern, level in self.access.items():
            if fnmatchcase(path, pattern):
                return level
        return Access.READ


_RANK = [Access.READ, Access.PROPOSE, Access.TIDY, Access.WRITE]
_TOOL_FOR_ACTION = {action: g.id for g in CATALOG for action in g.actions}


class AgentPolicy:
    """The permission questions the platform asks about an agent write, answered from the
    run's contracts (the built-ins when none are given). Unknown agents may do nothing."""

    def __init__(self, specs: Iterable[AgentSpec] | None = None) -> None:
        from .builtins import builtin_specs  # builtins import this module

        self.specs = {spec.handle: spec for spec in (specs if specs is not None else builtin_specs())}

    def spec(self, handle: str) -> AgentSpec | None:
        return self.specs.get(handle)

    def access(self, handle: str, path: str) -> Access:
        spec = self.spec(handle)
        return spec.folder_access(path) if spec else Access.READ

    def can_write(self, handle: str, path: str) -> bool:
        """Whether the agent may write the file itself (WRITE, or TIDY for tidying roles)."""
        return self.access(handle, path) in (Access.WRITE, Access.TIDY)

    def can_create_issue(self, handle: str, issue_type: str) -> bool:
        spec = self.spec(handle)
        return bool(spec and spec.can("issues.create") and issue_type in spec.issue_types)

    def can_edit_issues(self, handle: str) -> bool:
        spec = self.spec(handle)
        return bool(spec and spec.can("issues.update"))

    def can_comment(self, handle: str) -> bool:
        spec = self.spec(handle)
        return bool(spec and spec.can("issues.comment"))

    def allowed(self, handle: str, action: str) -> bool:
        """Whether the agent may take `action` without a person approving it (a standing rule)."""
        spec = self.spec(handle)
        return bool(spec and spec.can(_TOOL_FOR_ACTION.get(action, action)) and spec.allowed(action))
