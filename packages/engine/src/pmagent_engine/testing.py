"""Test helpers: a scripted chat model, so agent runs can be tested without an API key."""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from pydantic import Field


def _chunks(message: AIMessage) -> list[Any]:
    """A reply as stream chunks: text word by word (so streaming shows up in tests), or a
    tool call or a list of content blocks (e.g. `[]`, as Gemini sometimes ends a turn) in one
    piece. A scripted `usage_metadata` rides on the last chunk, as providers report it."""
    chunks = _content_chunks(message)
    if message.usage_metadata:
        chunks[-1].message.usage_metadata = message.usage_metadata
    return chunks


def _content_chunks(message: AIMessage) -> list[Any]:
    import json

    from langchain_core.messages import AIMessageChunk
    from langchain_core.outputs import ChatGenerationChunk

    if message.tool_calls:
        return [
            ChatGenerationChunk(
                message=AIMessageChunk(
                    content=message.content,
                    tool_call_chunks=[
                        {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i}
                        for i, c in enumerate(message.tool_calls)
                    ],
                )
            )
        ]
    if isinstance(message.content, list):
        return [ChatGenerationChunk(message=AIMessageChunk(content=message.content))]
    words = str(message.content).split(" ")
    return [
        ChatGenerationChunk(message=AIMessageChunk(content=w if i == 0 else f" {w}"))
        for i, w in enumerate(words)
    ]


class _StreamsReplies:
    """Stream what `_generate` would reply (the fake models' own streaming can't do tool calls)."""

    def _stream(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        message = self._generate(messages, *args, **kwargs).generations[0].message  # type: ignore[attr-defined]
        yield from _chunks(message)

    async def _astream(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        for chunk in self._stream(messages, *args, **kwargs):
            yield chunk


class ScriptedChatModel(_StreamsReplies, GenericFakeChatModel):
    """Replies with the given messages in order; tool binding is accepted and ignored.

    Script tool use with `tool_call(...)`, e.g. the PM writing a file:
        ScriptedChatModel.of(tool_call("write_file", file_path="/pmagent/x.md", content="..."),
                             "Done: wrote x.md")
    """

    received: list[list[BaseMessage]] = Field(default_factory=list)
    """Every prompt the model was called with, for assertions."""
    tools_received: list[list[str]] = Field(default_factory=list)
    """The names of the tools offered with each prompt (same order as `received`)."""
    bound: list[str] = Field(default_factory=list)

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedChatModel:  # type: ignore[override]
        from .catalog import tool_name

        # Each agent binds its tools right before calling the model; remember them for that call.
        return self.model_copy(update={"bound": [tool_name(t) for t in tools]}) if tools else self

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        self.received.append(list(messages))
        self.tools_received.append(list(self.bound))
        return super()._generate(messages, *args, **kwargs)

    @classmethod
    def of(cls, *replies: AIMessage | str) -> ScriptedChatModel:
        messages: Iterable[AIMessage] = (
            r if isinstance(r, AIMessage) else AIMessage(content=r) for r in replies
        )
        return cls(messages=iter(list(messages)))


def tool_call(name: str, call_id: str | None = None, **args: Any) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id or f"call_{name}", "type": "tool_call"}],
    )


class RuleBasedChatModel(_StreamsReplies, GenericFakeChatModel):
    """A deterministic model for end-to-end (browser) tests, driven by the conversation itself
    rather than a script, so it behaves the same across processes, resumes, and restarts:

    - "create issue: <title>" asks to create that task (an Action Mode write, so it pauses
      for approval); after the tool runs, it confirms.
    - "plan: <step>; <step>; ..." stops at a checkpoint with those steps, for the person to
      continue, change the plan, or stop; then it says what it heard.
    - "research: <question>" searches the web, reads the first result, and records a report:
      one claim quoted from the page and one that isn't on it (the check marks it unsupported).
    - anything else is echoed: "Test model reply: <message>".

    Enabled only when the backend runs with PMAGENT_E2E_MODELS=true (never in production).
    """

    messages: Any = Field(default_factory=lambda: iter(()))

    def bind_tools(self, tools: Any, **kwargs: Any) -> RuleBasedChatModel:  # type: ignore[override]
        return self

    def _reply(self, messages: list[BaseMessage]) -> AIMessage:
        last = messages[-1] if messages else None
        if last is not None and last.type == "tool":
            return self._after_tool(str(getattr(last, "name", "") or ""), str(last.content))
        text = str(last.content if last is not None else "").strip()
        lowered = text.lower()
        if lowered.startswith("create issue:"):
            title = text.split(":", 1)[1].strip() or "Untitled"
            return tool_call("create_issue", type="task", title=title, priority="medium")
        if lowered.startswith("research:"):
            return tool_call("web_search", query=text.split(":", 1)[1].strip() or "research")
        if lowered.startswith("plan:"):
            steps = [s.strip() for s in text.split(":", 1)[1].split(";") if s.strip()] or ["Do it"]
            return tool_call("checkpoint", summary="A plan for this request", plan=steps)
        return AIMessage(content=f"Test model reply: {text[:500]}")

    def _after_tool(self, name: str, content: str) -> AIMessage:
        if name == "web_search" and (url := re.search(r"https?://\S+", content)):
            return tool_call("fetch_page", url=url.group(0))
        if name == "fetch_page" and (label := re.search(r"\[(S\d+)\]", content)):
            body = content.split("<web_content", 1)[-1].split(">", 1)[-1]
            quote = next((s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if len(s.split()) >= 5), "")
            claims = [(quote.rstrip("."), quote), ("It changes every month", "This sentence is not on the page.")]
            return tool_call("submit_result", items=[
                {"claim": claim, "sources": [label.group(1)], "confidence": "high",
                 "quotes": [{"source": label.group(1), "text": text}]}
                for claim, text in claims
            ])
        if name == "submit_result":
            return AIMessage(content="Research done: the findings and their sources are below.")
        return AIMessage(content=f"Done. {content[:200]}")

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        from langchain_core.outputs import ChatGeneration, ChatResult

        return ChatResult(generations=[ChatGeneration(message=self._reply(messages))])
