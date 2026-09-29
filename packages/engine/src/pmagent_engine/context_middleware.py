"""Middleware that keeps an agent's prompt small (plan Phase 2, "agent context").

- `UnchangedReads`: reading a file the agent already has in its conversation, unchanged,
  returns a one-line note instead of the whole file again.
- `summarization()`: a long conversation's older turns are summarised once its prompt passes
  a token threshold, keeping the recent turns word for word (deepagents' summarisation,
  whose own default waits until 85% of the model's context window: far too late to save
  anything on a 1M-token model).

Built against deepagents 0.7.19 (pinned <0.8).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from deepagents.middleware.summarization import (
    SUMMARIZATION_EVENT_KEY,
    SummarizationMiddleware,
    _DeepAgentsSummarizationMiddleware,
)
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage

UNCHANGED_NOTE = (
    "{path} is unchanged since you read it earlier in this conversation (the same lines are "
    "above); use that copy."
)


def _key(args: Any) -> tuple[Any, ...] | None:
    if not isinstance(args, dict) or not isinstance(args.get("file_path"), str):
        return None
    return (args["file_path"], args.get("offset") or 0, args.get("limit"))


def earlier_read(messages: list[Any], key: tuple[Any, ...]) -> str | None:
    """What an earlier read_file with the same arguments returned, if it's still in the
    conversation the model sees."""
    calls: dict[str, tuple[Any, ...] | None] = {}
    found: str | None = None
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls or []:
                if call.get("name") == "read_file" and call.get("id"):
                    calls[call["id"]] = _key(call.get("args"))
        elif isinstance(message, ToolMessage) and calls.get(message.tool_call_id) == key:
            if getattr(message, "status", "success") != "error" and isinstance(message.content, str):
                found = message.content  # the latest wins
    return found


class UnchangedReads(AgentMiddleware):
    """A read_file whose result is exactly what an earlier read_file (same file, same lines)
    returned in this conversation becomes a short note: the model already has those lines, and
    every copy is re-sent with each later call. Content is compared, so a file that changed
    since is always returned in full; reads that were summarised away don't count."""

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        result = await handler(request)
        return self._check(request, result)

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        return self._check(request, handler(request))

    def _check(self, request: Any, result: Any) -> Any:
        call = request.tool_call
        key = _key(call.get("args")) if call.get("name") == "read_file" else None
        if key is None or not isinstance(result, ToolMessage) or not isinstance(result.content, str):
            return result
        if getattr(result, "status", "success") == "error" or len(result.content) < len(UNCHANGED_NOTE) * 2:
            return result
        state = request.state or {}
        messages = _DeepAgentsSummarizationMiddleware._apply_event_to_messages(
            list(state.get("messages") or []), state.get(SUMMARIZATION_EVENT_KEY)
        )
        if earlier_read(messages, key) != result.content:
            return result
        return ToolMessage(
            content=UNCHANGED_NOTE.format(path=key[0]),
            tool_call_id=result.tool_call_id,
            name=result.name,
        )


# The model is sent every tool's definition with every call. deepagents' file tools describe
# features a project's Markdown knowledge doesn't use (regex via `execute`, images and PDFs,
# offloaded results), so they get shorter descriptions here; how they work doesn't change.
SHORT_DESCRIPTIONS = {
    "ls": "List the files and folders in a directory (absolute path, e.g. /pmagent/requirements/).",
    "read_file": (
        "Read a file (absolute path), 100 lines at a time by default; page with `offset`/`limit`. "
        "Read several files in one step when you need them. For a long document, prefer "
        "`document_outline` and `read_section` when you have them."
    ),
    "glob": (
        "Find files by name pattern, e.g. `*.md`, `/pmagent/requirements/**/*.md`, "
        "`/pmagent/decisions/*.md`. Returns absolute paths."
    ),
    "grep": (
        "Search files for LITERAL text (not a regex; run one grep per alternative). "
        "Narrow with `path` and `glob`. To find a topic in other words, use `search_knowledge` "
        "when you have it."
    ),
}
# Agents never delete project knowledge (a person does); the backend refuses it anyway.
EXCLUDED_TOOLS = frozenset({"delete", "execute"})


def _compact(tool: Any) -> Any:
    name = getattr(tool, "name", None)
    if name in SHORT_DESCRIPTIONS and hasattr(tool, "model_copy"):
        return tool.model_copy(update={"description": SHORT_DESCRIPTIONS[name]})
    return tool


class CompactTools(AgentMiddleware):
    """Sends the model fewer, shorter tool definitions (see SHORT_DESCRIPTIONS)."""

    def _request(self, request: Any) -> Any:
        tools = [
            _compact(tool)
            for tool in request.tools or []
            if getattr(tool, "name", None) not in EXCLUDED_TOOLS
        ]
        return request.override(tools=tools)

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        return await handler(self._request(request))

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        return handler(self._request(request))


def summarization(model: Any, backend: Any, after_tokens: int) -> Any:
    """deepagents' summarisation with our thresholds: summarise once the prompt (instructions,
    context, conversation) passes `after_tokens`, keeping about a quarter of that as recent
    turns. The older turns are saved in the run's scratch files, so the agent can reopen them."""
    return SummarizationMiddleware(
        model,
        backend=backend,
        trigger=("tokens", after_tokens),
        keep=("tokens", after_tokens // 4),
        trim_tokens_to_summarize=None,
        truncate_args_settings={"trigger": ("tokens", after_tokens * 3 // 4), "keep": ("messages", 10)},
    )
