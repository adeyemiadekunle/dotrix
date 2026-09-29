"""Keeping prompts small: unchanged re-reads and summarising long conversations."""
from pathlib import Path

from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from pmagent_engine.agent import build_team
from pmagent_engine.context_middleware import SHORT_DESCRIPTIONS, UNCHANGED_NOTE, earlier_read
from pmagent_engine.testing import ScriptedChatModel, tool_call

ROADMAP = "# Roadmap\n\n" + "\n".join(f"- Phase {i}: hubs, drivers and parcels in state {i}" for i in range(40))


def team(model, tmp_path: Path, **kwargs):
    (tmp_path / "roadmap.md").write_text(ROADMAP, encoding="utf-8")
    backend = CompositeBackend(
        default=StateBackend(), routes={"/pmagent/": FilesystemBackend(root_dir=tmp_path, virtual_mode=True)}
    )
    return build_team("Kunemi", "Logistics", model, backend, checkpointer=InMemorySaver(), **kwargs)


def config(thread: str) -> dict:
    return {"configurable": {"thread_id": thread}}


def tool_results(prompt: list) -> list[str]:
    return [m.content for m in prompt if isinstance(m, ToolMessage)]


async def test_reading_an_unchanged_file_again_returns_a_note(tmp_path: Path) -> None:
    model = ScriptedChatModel.of(
        tool_call("read_file", call_id="c1", file_path="/pmagent/roadmap.md"),
        tool_call("read_file", call_id="c2", file_path="/pmagent/roadmap.md"),
        tool_call("read_file", call_id="c3", file_path="/pmagent/roadmap.md", offset=5, limit=3),
        "Done.",
    )
    agent = team(model, tmp_path)
    await agent.ainvoke({"messages": [{"role": "user", "content": "roadmap?"}]}, config("t1"))
    first, second, other_lines = tool_results(model.received[3])
    assert "Phase 39" in first
    assert second == UNCHANGED_NOTE.format(path="/pmagent/roadmap.md")
    assert "Phase 4" in other_lines and "Phase 39" not in other_lines  # other lines: read them


async def test_a_new_conversation_turn_still_gets_the_note(tmp_path: Path) -> None:
    model = ScriptedChatModel.of(
        tool_call("read_file", call_id="c1", file_path="/pmagent/roadmap.md"),
        "Read it.",
        tool_call("read_file", call_id="c2", file_path="/pmagent/roadmap.md"),
        "Still the same.",
    )
    agent = team(model, tmp_path)
    await agent.ainvoke({"messages": [{"role": "user", "content": "read it"}]}, config("t2"))
    await agent.ainvoke({"messages": [{"role": "user", "content": "read it again"}]}, config("t2"))
    assert tool_results(model.received[3])[-1] == UNCHANGED_NOTE.format(path="/pmagent/roadmap.md")


def test_a_changed_file_is_not_unchanged() -> None:
    key = ("/pmagent/roadmap.md", 0, None)
    messages = [
        HumanMessage("hi"),
        AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"file_path": key[0]}, "id": "a"}]),
        ToolMessage(content="old lines", tool_call_id="a"),
    ]
    assert earlier_read(messages, key) == "old lines"
    assert earlier_read(messages, ("/pmagent/roadmap.md", 10, None)) is None  # other lines
    assert earlier_read(messages[:2], key) is None  # the result isn't there
    failed = [*messages[:2], ToolMessage(content="Error: not found", tool_call_id="a", status="error")]
    assert earlier_read(failed, key) is None


async def test_long_conversations_are_summarised(tmp_path: Path) -> None:
    model = ScriptedChatModel.of("Noted the hub list.", "There are 400 hubs.")
    summaries = ScriptedChatModel.of("SUMMARY: the user listed 400 hubs across Nigeria.")
    agent = team(model, tmp_path, specialist_model=summaries, summarize_after_tokens=6_000)
    hubs = "\n".join(f"Hub {i} in state {i % 36} handles {i * 17} parcels a day." for i in range(400))
    await agent.ainvoke({"messages": [{"role": "user", "content": hubs}]}, config("t3"))
    await agent.ainvoke({"messages": [{"role": "user", "content": "How many hubs?"}]}, config("t3"))
    assert len(summaries.received) == 1  # the summary is made by the cheaper model
    last_prompt = "\n".join(str(m.content) for m in model.received[-1])
    assert "SUMMARY: the user listed 400 hubs" in last_prompt
    assert "Hub 399 in state" not in last_prompt  # the long turn itself is gone
    assert "How many hubs?" in last_prompt  # recent turns are kept word for word


class RecordsTools(ScriptedChatModel):
    """Also records the tools each call was offered."""

    offered: list[list] = []

    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        type(self).offered.append(list(tools))
        return self


async def test_the_model_gets_fewer_shorter_tool_definitions(tmp_path: Path) -> None:
    RecordsTools.offered = []
    model = RecordsTools.of("ok")
    agent = team(model, tmp_path)
    await agent.ainvoke({"messages": [{"role": "user", "content": "hi"}]}, config("t5"))
    tools = {getattr(t, "name", None): t for t in RecordsTools.offered[-1]}
    assert "delete" not in tools and "execute" not in tools
    assert tools["grep"].description == SHORT_DESCRIPTIONS["grep"]
    assert "task" in tools and "write_file" in tools  # everything else is still there
