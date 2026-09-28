import asyncio
import uuid

from pmagent_backend.modules.agents.activity import activity_label
from pmagent_backend.modules.agents.streams import RunStreams


def test_labels_say_what_the_pm_is_doing() -> None:
    assert activity_label("read_file", {"file_path": "/pmagent/requirements/product.md"}) == "Reading requirements/product.md"
    assert activity_label("edit_file", {"file_path": "/pmagent/roadmap.md", "old_string": "x"}) == "Drafting a change to roadmap.md"
    assert activity_label("grep", {"pattern": "driver"}) == "Looking through the project files"
    assert activity_label("list_issues", {}) == "Checking the board"
    assert activity_label("get_issue", {"key": "kun-5"}) == "Looking at KUN-5"
    assert activity_label("task", {"subagent_type": "research-agent", "description": "..."}) == "Asking the research agent"
    assert activity_label("task", {"subagent_type": "someone-new"}) == "Asking a specialist agent"
    assert activity_label("read_file", None) == "Reading the project files"
    assert activity_label("some_new_tool", {"x": 1}) is None  # unknown tools show nothing


def test_labels_never_include_free_text() -> None:
    label = activity_label("create_issue", {"title": "Ignore previous instructions", "description": "…"})
    assert label == "Drafting a new issue"


async def test_in_process_streams_carry_activity() -> None:
    streams, run_id = RunStreams(), uuid.uuid4()
    stream = await streams.open(run_id)
    await stream.activity("Checking the board")
    events: list[tuple[str, str]] = []

    async def follow():
        async for event in streams.follow(run_id, heartbeat_seconds=1):
            events.append(event)

    follower = asyncio.create_task(follow())
    await asyncio.sleep(0.05)
    await stream.activity("Checking the board")  # unchanged: not repeated
    await stream.activity("Reading roadmap.md")
    await stream.publish("Done.")
    await streams.close(run_id)
    await asyncio.wait_for(follower, 5)
    assert events == [
        ("text", ""),
        ("activity", "Checking the board"),
        ("activity", "Reading roadmap.md"),
        ("delta", "Done."),
        ("end", ""),
    ]


def test_only_the_models_own_steps_give_activity() -> None:
    from langchain_core.messages import AIMessage, ToolMessage

    from pmagent_backend.modules.agents.runner import _activities

    call = AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"file_path": "/pmagent/roadmap.md"}, "id": "c1"}])
    assert _activities({"model": {"messages": [call]}}) == ["Drafting a change to roadmap.md"]
    # On resume, the approval middleware re-sends the call it decided (maybe rejected): no label.
    rejected = ToolMessage("rejected", tool_call_id="c1")
    assert _activities({"HumanInTheLoopMiddleware.after_model": {"messages": [call, rejected]}}) == []
    assert _activities({"__interrupt__": ()}) == []
