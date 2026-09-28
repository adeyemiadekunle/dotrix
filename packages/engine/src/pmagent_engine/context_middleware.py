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
