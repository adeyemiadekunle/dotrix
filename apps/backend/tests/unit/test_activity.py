import asyncio
import uuid

from dotrix_backend.modules.agents.activity import activity_label
from dotrix_backend.modules.agents.streams import RunStreams


def test_labels_say_what_the_pm_is_doing() -> None:
    assert activity_label("read_file", {"file_path": "/dotrix/requirements/product.md"}) == "Reading requirements/product.md"
    assert activity_label("edit_file", {"file_path": "/dotrix/roadmap.md", "old_string": "x"}) == "Drafting a change to roadmap.md"
    assert activity_label("grep", {"pattern": "driver"}) == "Looking through the project files"
    assert activity_label("list_issues", {}) == "Checking the board"
    assert activity_label("get_issue", {"key": "kun-5"}) == "Looking at KUN-5"
    assert activity_label("task", {"subagent_type": "research-agent", "description": "..."}) == "Asking the research agent"
    assert activity_label("task", {"subagent_type": "someone-new"}) == "Asking a specialist agent"
    assert activity_label("read_file", None) == "Reading the project files"
    assert activity_label("fetch_page", {"url": "https://www.gov.uk/guidance/vat"}) == "Reading gov.uk"
    assert activity_label("fetch_page", {"url": "not a url"}) == "Reading a web page"
    assert activity_label("code_search", {"pattern": "secret sauce"}) == "Searching the code"  # not the pattern
    assert activity_label("code_read", {"path": "/src/api/routes.py"}) == "Reading src/api/routes.py in the code"
    assert activity_label("code_tree", {"path": "."}) == "Looking through the code"
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

    from dotrix_backend.modules.agents.runner import _activities

    call = AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"file_path": "/dotrix/roadmap.md"}, "id": "c1"}])
    assert _activities({"model": {"messages": [call]}}) == ["Drafting a change to roadmap.md"]
    # On resume, the approval middleware re-sends the call it decided (maybe rejected): no label.
    rejected = ToolMessage("rejected", tool_call_id="c1")
    assert _activities({"HumanInTheLoopMiddleware.after_model": {"messages": [call, rejected]}}) == []
    assert _activities({"__interrupt__": ()}) == []


def test_stages_and_results_say_what_a_person_would() -> None:
    from langchain_core.messages import AIMessage, ToolMessage

    from dotrix_backend.modules.agents.activity import STAGE_LABELS, result_label
    from dotrix_backend.modules.agents.runner import _activities
    from dotrix_engine.outputs import PIPELINES

    assert {stage for stages in PIPELINES.values() for stage in stages} <= set(STAGE_LABELS)  # every stage has words
    assert activity_label("stage", {"current": "options"}) == "Considering options"
    assert activity_label("stage", {"current": "verify"}) == "Checking the facts against the sources"
    assert activity_label("stage", {"current": "made up by the model"}) is None
    assert result_label("task", {"subagent_type": "research-agent"}) == "Weighing what the research agent found"
    assert result_label("delegate_tasks", None) == "Weighing what the specialists found"
    assert result_label("read_file", {"file_path": "/dotrix/a.md"}) is None

    calls: dict = {}
    ask = AIMessage(content="", tool_calls=[{"name": "task", "args": {"subagent_type": "architecture-agent"}, "id": "t1"}])
    assert _activities({"model": {"messages": [ask]}}, calls) == ["Asking the architecture agent"]
    answer = ToolMessage("Use a queue.", tool_call_id="t1", name="task")
    assert _activities({"tools": {"messages": [answer]}}, calls) == ["Weighing what the architecture agent found"]



async def test_the_reply_says_it_is_being_written_once_it_starts() -> None:
    from langchain_core.messages import AIMessageChunk

    from dotrix_backend.modules.agents.activity import WRITING
    from dotrix_backend.modules.agents.runner import _run_graph

    class Graph:  # what the graph streams: a tool call's label, then the reply in two pieces
        async def astream(self, *_args, **_kwargs):
            from langchain_core.messages import AIMessage

            call = AIMessage(content="", tool_calls=[{"name": "list_issues", "args": {}, "id": "c1"}])
            yield "updates", {"model": {"messages": [call]}}
            for piece in ("Three issues ", "are open."):
                yield "messages", (AIMessageChunk(content=piece), {"lc_agent_name": "project-manager-agent"})
            yield "values", {"messages": []}

    streams, run_id = RunStreams(), uuid.uuid4()
    stream = await streams.open(run_id)
    seen: list[tuple[str, str]] = []

    async def follow():
        async for event in streams.follow(run_id, heartbeat_seconds=1):
            seen.append(event)

    follower = asyncio.create_task(follow())
    await asyncio.sleep(0.05)
    await _run_graph(Graph(), {}, {}, stream)
    await streams.close(run_id)
    await asyncio.wait_for(follower, 5)
    assert seen == [("text", ""), ("activity", "Checking the board"), ("activity", WRITING),
                    ("delta", "Three issues "), ("delta", "are open."), ("end", "")]
