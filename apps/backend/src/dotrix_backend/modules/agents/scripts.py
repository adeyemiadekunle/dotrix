"""Code mode for dotrix's own agents: `run_script`.

Instead of one tool call per model step, Nova can write a short script (a subset of Python) that calls the
project tools it already has, chains their results, runs independent calls at once (`asyncio.gather`) and
returns only what it needs. A task that took ten model steps can take one, and a large result can be filtered
before the model reads it, so long reads cost fewer round trips and less context.

What it may do is what the run may already do, and no more:
- Only read tools cross into a script (`READ_CAPABILITIES`): documents, search, the board, the graph and the
  code, each already filtered by the agent's contract. Changes stay ordinary tool calls, so every write still
  goes through approvals and the audit log one at a time.
- Each call is the very tool the run was given: on fx, a `RuntimeTool` that rechecks the binding, the person's
  access, the contract and the lease before and after the call; on DeepAgents, the same builders' functions.
- A refusal that means the run no longer owns the work, or the person no longer has the access (`Conflict`,
  `Forbidden`), ends the whole script and is raised to the runtime as that tool's failure: code can't catch it
  and carry on.
- The code runs in Monty (pydantic-monty), a separate interpreter in worker subprocesses: no files, network,
  environment, subprocesses or imports beyond its own small library (checked on 1.4.0), within time, memory,
  recursion and call limits (`LIMITS`), and a wall-clock limit for the whole script.
- Every call is reported (`on_call`) so the run's activity shows each step, as for an ordinary tool call.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import date, datetime
from enum import Enum
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from dotrix_backend.core.errors import Conflict, Forbidden
from dotrix_engine.catalog import tool_id
from dotrix_engine.runtimes import RuntimeTool, RuntimeToolContext

SCRIPT_TOOL = "run_script"
# The catalogue ids whose tools a script may call: reads only (dotrix_engine.catalog).
READ_CAPABILITIES = frozenset({"knowledge.read", "knowledge.search", "board.read", "graph.read", "code.read"})
# Inside the sandbox: execution time per script and per host round trip, memory, recursion, and how many
# times it may come back to the host (each tool call is one).
LIMITS = {
    "max_feed_duration_secs": 10.0,
    "max_turn_duration_secs": 10.0,
    "max_memory": 64 * 1024 * 1024,
    "max_recursion_depth": 200,
    "max_suspensions": 40,
    "max_total_sleep_secs": 0.0,
}
WALL_SECONDS = 120  # the whole script, tool calls included (the sandbox's clock stops while they run)
MAX_RESULT = 20_000  # characters of result (and of printed output) handed back to the model

ScriptFunction = Callable[[dict[str, Any]], Awaitable[Any]]
OnCall = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclasses.dataclass(frozen=True)
class ScriptFunctionSpec:
    """A tool a script may call: its name, what it does, its arguments (JSON schema), and how to call it."""

    name: str
    description: str
    schema: dict[str, Any]
    call: ScriptFunction


class ScriptAborted(Exception):
    """The script ended because the run lost the work or the person lost access (the cause is attached)."""


def _plain(value: Any) -> Any:
    """A tool's result as plain data the sandbox can hold: dicts, lists, strings, numbers, booleans, None."""
    def default(item: Any) -> Any:
        if isinstance(item, BaseModel):
            return item.model_dump(mode="json")
        if dataclasses.is_dataclass(item) and not isinstance(item, type):
            return dataclasses.asdict(item)
        if isinstance(item, (uuid.UUID, datetime, date)):
            return str(item)
        if isinstance(item, Enum):
            return item.value
        if isinstance(item, (set, frozenset, tuple)):
            return list(item)
        return str(item)
    return json.loads(json.dumps(value, default=default))


def _clip(text: str, limit: int = MAX_RESULT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… ({len(text) - limit} more characters cut: return less, or filter it in the script)"


def _type(schema: dict[str, Any]) -> str:
    kind = schema.get("type")
    if isinstance(kind, list):
        return " | ".join(str(k) for k in kind)
    if "anyOf" in schema:
        return " | ".join(_type(option) for option in schema["anyOf"] if isinstance(option, dict))
    return {"string": "str", "integer": "int", "number": "float", "boolean": "bool", "array": "list",
            "object": "dict", "null": "None"}.get(str(kind), "Any")


def signature(spec: ScriptFunctionSpec) -> str:
    """How a function reads in the tool's description: `name(arg: type, opt: type = default)` and its summary."""
    properties = spec.schema.get("properties") or {}
    required = set(spec.schema.get("required") or [])
    args = []
    for name, prop in properties.items():
        prop = prop if isinstance(prop, dict) else {}
        piece = f"{name}: {_type(prop)}"
        if name not in required:
            piece += f" = {json.dumps(prop.get('default'))}" if "default" in prop else " = None"
        args.append(piece)
    summary = (spec.description or "").strip().split("\n")[0][:160]
    return f"await {spec.name}({', '.join(args)})" + (f"  # {summary}" if summary else "")


def describe(functions: list[ScriptFunctionSpec]) -> str:
    listed = "\n".join(signature(spec) for spec in functions)
    return (
        "Run a short script (a subset of Python) that calls your read tools, so several reads take one step. "
        "Use it to chain reads (one result picks the next), to run independent reads at once with "
        "`await asyncio.gather(...)`, and to filter large results down to what you need before you read them. "
        "Call the functions with keyword arguments and `await`; they return plain data (dicts and lists). "
        "The script's last expression is returned to you (keep it short: a list of the parts you need, not "
        "whole documents); `print` also reaches you. It has no files or network; it can import small standard "
        "modules such as `asyncio`, `json`, `re`, `math`, `datetime`, `collections` and `itertools`. It can only "
        "read: make changes with your other tools, one at a time. When you don't know what a function returns, "
        "return a small part of it first (its keys, or one item), rather than guessing. "
        f"Up to {LIMITS['max_suspensions']} calls and {WALL_SECONDS} s per script.\n\nFunctions:\n{listed}"
    )


async def run_script(code: str, functions: Mapping[str, ScriptFunctionSpec], *, on_call: OnCall | None = None) -> str:
    """Run `code` with `functions` as its only way out. Returns what the model reads; raises ScriptAborted
    (from the cause) when a call found the run no longer owns the work or the person lost access."""
    from pydantic_monty import AsyncMonty, MontyError

    if not code.strip():
        return "The script was empty."
    fatal: list[BaseException] = []
    calls = [0]

    def wrap(spec: ScriptFunctionSpec) -> Callable[..., Awaitable[Any]]:
        async def call(*args: Any, **kwargs: Any) -> Any:
            if args:
                raise TypeError(f"Call {spec.name} with keyword arguments, e.g. {spec.name}(name=value)")
            if fatal:  # a call after the run lost the work: stop at once
                raise RuntimeError("The script was stopped")
            calls[0] += 1
            if on_call is not None:
                await on_call(spec.name, dict(kwargs))
            try:
                return _plain(await spec.call(dict(kwargs)))
            except (Conflict, Forbidden) as exc:
                fatal.append(exc)
                raise RuntimeError("The script was stopped") from None
        call.__name__ = spec.name
        return call

    printed: list[str] = []

    def on_print(_stream: str, text: str) -> None:
        if sum(len(part) for part in printed) < MAX_RESULT:
            printed.append(text)

    lookup = {name: wrap(spec) for name, spec in functions.items()}
    try:
        async with AsyncMonty(request_timeout=WALL_SECONDS + 10) as pool, pool.checkout(limits=dict(LIMITS)) as session:
            result = await asyncio.wait_for(
                session.feed_run(code, external_lookup=lookup, print_callback=on_print), timeout=WALL_SECONDS,
            )
    except TimeoutError:
        if fatal:
            raise ScriptAborted(str(fatal[0])) from fatal[0]
        return _report(None, printed, calls[0], f"The script didn't finish within {WALL_SECONDS} seconds and was stopped.")
    except MontyError as exc:
        if fatal:
            raise ScriptAborted(str(fatal[0])) from fatal[0]
        return _report(None, printed, calls[0], f"The script failed:\n{_error_text(exc)}")
    if fatal:
        raise ScriptAborted(str(fatal[0])) from fatal[0]
    return _report(result, printed, calls[0], None)


def _error_text(exc: Exception) -> str:
    display = getattr(exc, "display", None)
    try:
        text = display() if callable(display) else str(exc)
    except Exception:  # noqa: BLE001 - the plain message is enough
        text = str(exc)
    return _clip(str(text), 4000)


def _report(result: Any, printed: list[str], calls: int, failure: str | None) -> str:
    parts = []
    if printed:
        parts.append("Printed:\n" + _clip("".join(printed)))
    if failure is not None:
        parts.append(failure)
    else:
        try:
            shown = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            shown = str(result)
        parts.append("Result:\n" + _clip(shown))
    parts.append(f"({calls} tool call{'s' if calls != 1 else ''})")
    return "\n\n".join(parts)


SCRIPT_GUIDE = """

## Scripts

When a task needs several reads (a search, then the documents it found; every open issue that mentions
something; the same lookup for several names), use `run_script` to do them in one step: call the functions with
`await`, run independent ones together with `asyncio.gather`, and return only the parts you need. Keep using the
ordinary tools for a single read, and always for changes."""


class ScriptArgs(BaseModel):
    code: str = Field(description="The script: a subset of Python. Its last expression is returned.")


def _readable(name: str, capability: str | None, can: Callable[[str], bool]) -> bool:
    return capability in READ_CAPABILITIES and can(capability) and name != SCRIPT_TOOL


def script_runtime_tool(read_tools: list[RuntimeTool], *, on_call: OnCall | None = None) -> RuntimeTool | None:
    """`run_script` for an fx turn, over the turn's own read tools (each one rechecks the binding, access, contract
    and lease around its call). None when there is nothing it could read."""
    readable = [tool for tool in read_tools
                if not tool.writes and tool.execute_scoped is not None and _readable(tool.name, tool_id(tool), lambda _: True)]
    if not readable:
        return None
    listed = [ScriptFunctionSpec(tool.name, tool.description, tool.input_schema, _unused) for tool in readable]

    async def execute(arguments: dict, context: RuntimeToolContext) -> str:
        def bound(tool: RuntimeTool) -> ScriptFunction:
            async def call(args: dict[str, Any]) -> Any:
                assert tool.execute_scoped is not None
                return await tool.execute_scoped(args, context)
            return call

        functions = {tool.name: ScriptFunctionSpec(tool.name, tool.description, tool.input_schema, bound(tool))
                     for tool in readable}
        try:
            return await run_script(str(arguments.get("code") or ""), functions, on_call=on_call)
        except ScriptAborted as exc:
            raise (exc.__cause__ or exc) from None

    return RuntimeTool(SCRIPT_TOOL, describe(listed), ScriptArgs.model_json_schema(), execute_scoped=execute,
                       idempotent=True, writes=False)


def script_tool(functions: list, *, can: Callable[[str], bool], on_call: OnCall | None = None) -> StructuredTool | None:
    """`run_script` for DeepAgents, over the same read tools the agent was given (`functions`: plain coroutines or
    LangChain tools), keeping only reads its contract allows (`can`). None when there is nothing it could read."""
    tools: dict[str, StructuredTool] = {}
    for fn in functions:
        tool = fn if isinstance(fn, StructuredTool) else StructuredTool.from_function(coroutine=fn)
        if _readable(tool.name, tool_id(tool), can):
            tools.setdefault(tool.name, tool)
    if not tools:
        return None
    specs = {name: ScriptFunctionSpec(name, tool.description, tool.args_schema.model_json_schema(), tool.ainvoke)
             for name, tool in tools.items()}

    async def run(code: str) -> str:
        try:
            return await run_script(code, specs, on_call=on_call)
        except ScriptAborted as exc:
            raise (exc.__cause__ or exc) from None

    return StructuredTool.from_function(coroutine=run, name=SCRIPT_TOOL, description=describe(list(specs.values())),
                                        args_schema=ScriptArgs)


async def _unused(_: dict[str, Any]) -> Any:  # a listed function's call, for its description only
    raise RuntimeError("not callable")
