"""Test helpers: a scripted chat model, so agent runs can be tested without an API key."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from pydantic import Field


class ScriptedChatModel(GenericFakeChatModel):
    """Replies with the given messages in order; tool binding is accepted and ignored.

    Script tool use with `tool_call(...)`, e.g. the PM writing a file:
        ScriptedChatModel.of(tool_call("write_file", file_path="/pmagent/x.md", content="..."),
                             "Done: wrote x.md")
    """

    received: list[list[BaseMessage]] = Field(default_factory=list)
    """Every prompt the model was called with, for assertions."""

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedChatModel:  # type: ignore[override]
        return self

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        self.received.append(list(messages))
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


class RuleBasedChatModel(GenericFakeChatModel):
    """A deterministic model for end-to-end (browser) tests, driven by the conversation itself
    rather than a script, so it behaves the same across processes, resumes, and restarts:

    - "create issue: <title>" asks to create that task (an Action Mode write, so it pauses
      for approval); after the tool runs, it confirms.
    - a conversation-title request gets "Test conversation".
    - anything else is echoed: "Test model reply: <message>".

    Enabled only when the backend runs with PMAGENT_E2E_MODELS=true (never in production).
    """

    messages: Any = Field(default_factory=lambda: iter(()))

    def bind_tools(self, tools: Any, **kwargs: Any) -> RuleBasedChatModel:  # type: ignore[override]
        return self

    def _reply(self, messages: list[BaseMessage]) -> AIMessage:
        last = messages[-1] if messages else None
        if last is not None and last.type == "tool":
            return AIMessage(content=f"Done. {str(last.content)[:200]}")
        text = str(last.content if last is not None else "").strip()
        if "Write a title for this conversation" in text:
            return AIMessage(content="Test conversation")
        lowered = text.lower()
        if lowered.startswith("create issue:"):
            title = text.split(":", 1)[1].strip() or "Untitled"
            return tool_call("create_issue", type="task", title=title, priority="medium")
        return AIMessage(content=f"Test model reply: {text[:500]}")

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        from langchain_core.outputs import ChatGeneration, ChatResult

        return ChatResult(generations=[ChatGeneration(message=self._reply(messages))])
