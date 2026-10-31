"""Framework-neutral types for host-owned agents, tools and conversation turns."""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

JsonObject = dict[str, Any]
ToolHandler = Callable[[JsonObject], Awaitable[Any]]
ScopedToolHandler = Callable[[JsonObject, "RuntimeToolContext"], Awaitable[Any]]
EventHandler = Callable[["RuntimeEvent"], Awaitable[None]]
_SESSION_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_AGENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def validate_session(session_id: str, message: str) -> None:
    if not _SESSION_ID.fullmatch(session_id) or not message.strip():
        raise ValueError("Session ID must be 1–128 letters, digits, '.', '_' or '-'; message must be nonempty")


@dataclass(frozen=True)
class RuntimeToolContext:
    """Runtime correlation only; the host must supply and verify authorization separately."""

    session_id: str
    execution_id: str | None = None


@dataclass(frozen=True)
class RuntimeTool:
    """A host tool. The handler must validate inputs and enforce its own permissions."""

    name: str
    description: str
    input_schema: JsonObject
    execute: ToolHandler | None = None
    idempotent: bool = False
    writes: bool = True
    execute_scoped: ScopedToolHandler | None = None
    # The host may end the turn from this tool (RuntimeHandoff) to finish its work elsewhere, e.g. a
    # change waiting for a person's approval. Such a tool must be safe to run again under the same
    # execution ID: it is retried when the turn resumes.
    hands_off: bool = False

    def __post_init__(self) -> None:
        if (self.execute is None) == (self.execute_scoped is None):
            raise ValueError("Provide exactly one tool handler")


@dataclass(frozen=True)
class AgentRuntimeConfig:
    """One Dotrix agent's runtime configuration. Credentials remain with the host."""

    name: str
    instructions: str
    tools: tuple[RuntimeTool, ...] = ()

    def __post_init__(self) -> None:
        if not _AGENT_NAME.fullmatch(self.name) or not self.instructions.strip():
            raise ValueError("A valid agent name and nonempty instructions are required")
        names = [tool.name for tool in self.tools]
        if len(set(names)) != len(names) or any(not _TOOL_NAME.fullmatch(name) for name in names):
            raise ValueError("Tool names must be valid and unique")


@dataclass(frozen=True)
class RuntimeCapabilities:
    persistent_sessions: bool = False
    crash_recovery: bool = False
    approvals: bool = False
    streaming: bool = False
    cancellation: bool = False
    resume: bool = False
    steering: bool = False


class UnsupportedRuntimeOperation(RuntimeError):
    """An operation the selected runtime cannot provide in this configuration."""


@dataclass(frozen=True)
class RuntimeJournalSnapshot:
    checkpoint: tuple[str, bytes] | None
    records: tuple[tuple[str, bytes], ...]


class RuntimeJournalStore(Protocol):
    """Opaque journal storage owned and authorized by the host."""

    async def load(self) -> RuntimeJournalSnapshot: ...

    async def append(self, *, expected: str | None, idempotency_key: str, data: bytes) -> str: ...

    async def save_checkpoint(self, *, through: str, data: bytes) -> None: ...


@dataclass(frozen=True)
class RuntimeHandoff:
    """A host tool has saved work that must complete outside this runtime process."""


@dataclass(frozen=True)
class RuntimeEvent:
    type: Literal["turn_accepted", "text_delta", "reasoning_delta", "tool_start", "tool_end"]
    session_id: str
    text: str = ""
    tool: str | None = None
    message_id: str | None = None


@dataclass(frozen=True)
class TurnResult:
    text: str
    stop_reason: str
    usage: Mapping[str, int] | None = None
    tools: tuple[str, ...] = field(default_factory=tuple)
    message_id: str | None = None
    repeated: bool = False
    handoff: str | None = None


class ConversationRuntime(Protocol):
    capabilities: RuntimeCapabilities

    async def new_session(self) -> str: ...

    async def prompt(self, session_id: str, message: str, *, on_event: EventHandler | None = None) -> TurnResult: ...

    async def resume(self, session_id: str, *, on_event: EventHandler | None = None) -> TurnResult: ...

    async def steer(self, session_id: str, message: str) -> None: ...

    async def cancel(self, session_id: str) -> None: ...

    async def close(self) -> None: ...
