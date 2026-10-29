"""A DeepAgents conversation with only the host's explicitly supplied tools."""
from __future__ import annotations

import asyncio
import contextvars
import json
import uuid
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver

from .contracts import (
    AgentRuntimeConfig,
    EventHandler,
    RuntimeCapabilities,
    RuntimeEvent,
    RuntimeToolContext,
    TurnResult,
    UnsupportedRuntimeOperation,
    validate_session,
)

_SESSION = contextvars.ContextVar("runtime_session", default=None)


class _ToolBoundary(AgentMiddleware):
    def __init__(self, allowed: set[str]):
        self.allowed = allowed

    def _filter(self, request):
        return request.override(tools=[t for t in request.tools if getattr(t, "name", None) in self.allowed])

    def wrap_model_call(self, request, handler):
        return handler(self._filter(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._filter(request))

    def _reject(self, request):
        if request.tool_call["name"] not in self.allowed:
            return ToolMessage(content="Tool unavailable.", tool_call_id=request.tool_call["id"], status="error")
        return None

    def wrap_tool_call(self, request, handler):
        return self._reject(request) or handler(request)

    async def awrap_tool_call(self, request, handler):
        return self._reject(request) or await handler(request)


class DeepAgentsRuntime:
    """In-memory prototype. It does not replace Dotrix's durable production graph."""

    capabilities = RuntimeCapabilities(streaming=True, cancellation=True)

    def __init__(self, config: AgentRuntimeConfig, model: Any):
        tools = []
        for spec in config.tools:
            async def invoke(_spec=spec, **arguments):
                try:
                    if _spec.execute_scoped:
                        session_id = _SESSION.get()
                        if session_id is None:
                            raise RuntimeError("Tool call has no active session")
                        result = await _spec.execute_scoped(arguments, RuntimeToolContext(session_id))
                    else:
                        assert _spec.execute is not None
                        result = await _spec.execute(arguments)
                except Exception:
                    return "Tool failed."
                return result if isinstance(result, str) else json.dumps(result)

            tools.append(StructuredTool.from_function(
                coroutine=invoke, name=spec.name, description=spec.description, args_schema=spec.input_schema,
            ))
        self.graph = create_deep_agent(
            model=model, system_prompt=config.instructions, tools=tools, backend=StateBackend(),
            checkpointer=InMemorySaver(), subagents=[], middleware=[_ToolBoundary({t.name for t in config.tools})],
        )
        self._locks: dict[str, asyncio.Lock] = {}
        self._active: dict[str, asyncio.Task] = {}
        self._closed = False

    async def new_session(self) -> str:
        if self._closed:
            raise RuntimeError("Runtime is closed")
        return f"deepagents-{uuid.uuid4().hex}"

    async def prompt(self, session_id: str, message: str, *, on_event: EventHandler | None = None) -> TurnResult:
        if self._closed:
            raise RuntimeError("Runtime is closed")
        validate_session(session_id, message)
        async with self._locks.setdefault(session_id, asyncio.Lock()):
            if self._closed:
                raise RuntimeError("Runtime is closed")
            task = asyncio.current_task()
            assert task is not None
            self._active[session_id] = task
            try:
                return await self._prompt(session_id, message, on_event=on_event)
            finally:
                self._active.pop(session_id, None)

    async def _prompt(self, session_id: str, message: str, *, on_event: EventHandler | None) -> TurnResult:
        config = {"configurable": {"thread_id": session_id}, "recursion_limit": 150}
        previous = await self.graph.aget_state(config)
        count = len(previous.values.get("messages", [])) if previous.values else 0
        latest: dict = {}
        tools: list[str] = []
        token = _SESSION.set(session_id)
        try:
            async for mode, value in self.graph.astream(
                {"messages": [{"role": "user", "content": message}]}, config,
                stream_mode=["messages", "updates", "values"],
            ):
                if mode == "values":
                    latest = value
                elif mode == "messages":
                    chunk, _ = value
                    if isinstance(chunk, AIMessageChunk) and isinstance(chunk.content, str) and chunk.content and on_event:
                        await on_event(RuntimeEvent("text_delta", session_id, text=chunk.content))
                elif mode == "updates" and isinstance(value, dict):
                    for output in value.values():
                        if not isinstance(output, dict):
                            continue
                        messages = output.get("messages")
                        for item in messages if isinstance(messages, list) else []:
                            if isinstance(item, AIMessage):
                                for call in item.tool_calls:
                                    tools.append(call["name"])
                                    if on_event:
                                        await on_event(RuntimeEvent("tool_start", session_id, tool=call["name"]))
                            elif isinstance(item, ToolMessage) and on_event:
                                await on_event(RuntimeEvent("tool_end", session_id, tool=item.name))
        finally:
            _SESSION.reset(token)
        messages = latest.get("messages", [])[count:]
        ai = [item for item in messages if isinstance(item, AIMessage)]
        if not ai:
            raise RuntimeError("DeepAgents returned no model response")
        final = ai[-1]
        reason = final.response_metadata.get("finish_reason") or "stop"
        usage = [item.usage_metadata for item in ai if item.usage_metadata]
        totals = ({"input_tokens": sum(u.get("input_tokens", 0) for u in usage),
                   "output_tokens": sum(u.get("output_tokens", 0) for u in usage)}
                  if len(usage) == len(ai) else None)
        content = final.content if isinstance(final.content, str) else final.text
        return TurnResult(text=content, stop_reason="end_turn" if reason == "stop" else reason,
                          usage=totals, tools=tuple(tools))

    async def resume(self, session_id: str, *, on_event: EventHandler | None = None) -> TurnResult:
        raise UnsupportedRuntimeOperation("The in-memory DeepAgents runtime cannot resume interrupted turns")

    async def steer(self, session_id: str, message: str) -> None:
        raise UnsupportedRuntimeOperation("The in-memory DeepAgents runtime does not support steering")

    async def cancel(self, session_id: str) -> None:
        if task := self._active.get(session_id):
            task.cancel()

    async def close(self) -> None:
        self._closed = True
        for task in self._active.values():
            task.cancel()
