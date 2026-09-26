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
