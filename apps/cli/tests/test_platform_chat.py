"""`dotrix chat` and `brief` against the platform's agents, with inline approvals."""
from __future__ import annotations

import sys
from pathlib import Path

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent))

from fake_platform import PID, WS, FakePlatform, approval  # noqa: E402

from dotrix_cli import cli as cli_module  # noqa: E402
from dotrix_cli.agent_client import PlatformAgent  # noqa: E402
from dotrix_cli.sync import LinkState  # noqa: E402

DIFF = "--- a/dotrix/roadmap.md\n+++ b/dotrix/roadmap.md\n@@ -1 +1,2 @@\n # Roadmap\n+Phase 1: core\n"


def agent(platform: FakePlatform, state: LinkState) -> PlatformAgent:
    return PlatformAgent(platform.client(), state, sleep=lambda s: None)


# -- the approval loop -------------------------------------------------------------------


def test_converse_settles_each_pause(platform: FakePlatform, state: LinkState) -> None:
    platform.agent_script = [
        {"status": "running"},
        {"status": "awaiting_approval", "approvals": [approval("a1"), approval("a2", target="/dotrix/vision.md")]},
        {"status": "queued"},  # after the decisions
        {"status": "completed", "reply": "Done: roadmap updated."},
    ]
    seen = []

    def decide(item, index, total):
        seen.append((item["id"], index, total))
        return ("approve", None) if item["id"] == "a1" else ("reject", "Keep the vision")

    run = agent(platform, state).start("update the roadmap")
    outcome = agent(platform, state).converse(run, decide)
    assert outcome.status == "completed" and outcome.run["reply"] == "Done: roadmap updated."
    assert seen == [("a1", 1, 2), ("a2", 2, 2)]
    assert platform.bodies("/decisions")[0]["decisions"] == [
        {"approval_id": "a1", "decision": "approve", "reason": None},
        {"approval_id": "a2", "decision": "reject", "reason": "Keep the vision"},
    ]


def test_approve_all(platform: FakePlatform, state: LinkState) -> None:
    platform.agent_script = [
        {"status": "awaiting_approval", "approvals": [approval(f"a{i}") for i in range(1, 4)]},
        {"status": "completed", "reply": "Created the epic and stories."},
    ]
    asked = []

    def decide(item, index, total):
        asked.append(item["id"])
        return "approve-all"

    outcome = agent(platform, state).converse(agent(platform, state).start("create them"), decide)
    assert asked == ["a1"]  # the rest were approved without asking
    assert [d["decision"] for d in platform.bodies("/decisions")[0]["decisions"]] == ["approve"] * 3
    assert outcome.status == "completed"


def test_always_allow_saves_the_rule_and_approves(platform: FakePlatform, state: LinkState) -> None:
    change = approval("a1") | {"agent": "product", "action": "knowledge.write"}
    platform.agent_script = [{"status": "awaiting_approval", "approvals": [change]}, {"status": "completed", "reply": "Ok."}]
    notes: list[str] = []
    outcome = agent(platform, state).converse(
        agent(platform, state).start("write it"), lambda *a: "always-allow", on_note=notes.append
    )
    assert outcome.status == "completed"
    assert any(r.url.path.endswith("/runs/run-1/approvals/a1/always-allow") for r in platform.requests)
    assert platform.bodies("/decisions")[0]["decisions"][0]["decision"] == "approve"
    assert notes == ["@product may now write documents without asking"]


def test_person_without_approve_permission_leaves_it_waiting(platform: FakePlatform, state: LinkState) -> None:
    platform.agent_script = [{"status": "awaiting_approval", "approvals": [approval("a1")]}]
    platform.deny_decisions = True
    outcome = agent(platform, state).converse(agent(platform, state).start("x"), lambda *a: ("approve", None))
    assert outcome.left_waiting and outcome.status == "awaiting_approval"


# -- the commands ----------------------------------------------------------------------


def test_chat_shows_the_diff_and_approves_inline(linked_repo: Path, platform: FakePlatform) -> None:
    platform.agent_script = [
        {"status": "awaiting_approval", "approvals": [approval("a1", diff=DIFF)]},
        # Like the real API, the finished run lists its decided approvals.
        {"status": "completed", "reply": "Roadmap updated with Phase 1.",
         "approvals": [approval("a1", diff=DIFF, status="approved")]},
    ]
    result = CliRunner().invoke(
        cli_module.app, ["chat", "--project", str(linked_repo)], input="Add phase 1 to the roadmap\na\n/quit\n"
    )
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Talking to the KUN team (Kunemi) on the platform" in out
    assert "The agents want to: write_file -> /dotrix/roadmap.md" in out
    assert "+Phase 1: core" in out
    assert "(1 change(s) approved, 0 rejected)" in out
    assert "Roadmap updated with Phase 1." in out
    assert "dotrix chat --thread thread-1" in out
    assert platform.runs_started == [{"message": "Add phase 1 to the roadmap"}]


def test_chat_reject_with_reason(linked_repo: Path, platform: FakePlatform) -> None:
    platform.agent_script = [
        {"status": "awaiting_approval", "approvals": [approval("a1", tool="create_issue", target="new epic: X",
                                                              args={"description": "Big idea"})]},
        {"status": "completed", "reply": "OK, nothing created."},
    ]
    result = CliRunner().invoke(
        cli_module.app, ["chat", "--project", str(linked_repo)], input="make an epic\nr\nNot yet\n/quit\n"
    )
    assert result.exit_code == 0, result.output
    assert "Big idea" in result.output  # the issue preview
    assert platform.bodies("/decisions")[0]["decisions"] == [
        {"approval_id": "a1", "decision": "reject", "reason": "Not yet"}
    ]


def test_brief_on_a_linked_repo(linked_repo: Path, platform: FakePlatform) -> None:
    platform.agent_script = [{"status": "running"}, {"status": "completed", "reply": "Phase: discovery. Nothing blocked."}]
    result = CliRunner().invoke(cli_module.app, ["brief", "--project", str(linked_repo)])
    assert result.exit_code == 0, result.output
    assert "Phase: discovery. Nothing blocked." in result.output
    # After checking the project is still in its workspace, the first thing is the briefing.
    assert platform.requests[0].url.path == f"/v1/workspaces/{WS}/projects/{PID}"
    assert platform.requests[1].url.path.endswith("/agent/briefing")


def test_brief_reports_a_failed_run(linked_repo: Path, platform: FakePlatform) -> None:
    platform.agent_script = [{"status": "failed", "error": "No API key for anthropic:claude-sonnet-5"}]
    result = CliRunner().invoke(cli_module.app, ["brief", "--project", str(linked_repo)])
    assert result.exit_code == 1 and "No API key" in result.output


# -- streaming the reply -------------------------------------------------------------------


def _collect() -> tuple[list[tuple[str, bool]], object]:
    pieces: list[tuple[str, bool]] = []
    return pieces, lambda text, new: pieces.append((text, new))


def test_the_reply_streams_as_it_is_written(platform: FakePlatform, state: LinkState) -> None:
    platform.agent_script = [{"status": "completed", "reply": "Three issues are open."}]
    platform.streams = [[("text", ""), ("delta", "Three issues "), ("delta", "are open.")]]
    pieces, on_text = _collect()
    outcome = agent(platform, state).converse(agent(platform, state).start("status?"), lambda *a: ("approve", None), on_text=on_text)
    assert pieces == [("Three issues ", True), ("are open.", False)]
    assert outcome.streamed == "Three issues are open." and outcome.reply_shown


def test_a_reconnect_only_shows_what_is_new(platform: FakePlatform, state: LinkState) -> None:
    # The first connection drops mid-reply (the run is still running), the second picks up.
    platform.agent_script = [{"status": "running"}, {"status": "completed", "reply": "Hello there."}]
    platform.streams = [[("text", "Hel")], [("text", "Hello"), ("delta", " there.")]]
    pieces, on_text = _collect()
    outcome = agent(platform, state).converse(agent(platform, state).start("hi"), lambda *a: ("approve", None), on_text=on_text)
    assert pieces == [("Hel", True), ("lo", False), (" there.", False)]
    assert outcome.reply_shown


def test_each_step_after_an_approval_is_a_new_message(platform: FakePlatform, state: LinkState) -> None:
    platform.agent_script = [
        {"status": "awaiting_approval", "approvals": [approval("a1")]},
        {"status": "queued"},
        {"status": "completed", "reply": "Roadmap updated."},
    ]
    platform.streams = [[("text", "I'll update the roadmap.")], [("text", "Roadmap updated.")]]
    pieces, on_text = _collect()
    outcome = agent(platform, state).converse(agent(platform, state).start("go"), lambda *a: ("approve", None), on_text=on_text)
    assert pieces == [("I'll update the roadmap.", True), ("Roadmap updated.", True)]
    assert outcome.reply_shown


def test_without_streaming_it_falls_back_to_polling(platform: FakePlatform, state: LinkState) -> None:
    platform.stream_status = 404  # e.g. an older server
    platform.agent_script = [{"status": "running"}, {"status": "completed", "reply": "Done."}]
    pieces, on_text = _collect()
    outcome = agent(platform, state).converse(agent(platform, state).start("go"), lambda *a: ("approve", None), on_text=on_text)
    assert pieces == [] and outcome.status == "completed" and not outcome.reply_shown
    streams = [r for r in platform.requests if r.url.path.endswith("/stream")]
    assert len(streams) == 1  # it stopped trying


def test_chat_prints_the_streamed_reply_once(linked_repo: Path, platform: FakePlatform) -> None:
    platform.agent_script = [{"status": "completed", "reply": "Three issues are open."}]
    platform.streams = [[("text", "Three issues "), ("delta", "are open.")]]
    result = CliRunner().invoke(cli_module.app, ["chat", "--project", str(linked_repo)], input="status?\n/quit\n")
    assert result.exit_code == 0, result.output
    assert result.output.count("Three issues are open.") == 1
    assert "Three issues are open.\n" in result.output  # the line is ended before the next prompt


def test_chat_shows_the_saved_reply_when_nothing_streamed(linked_repo: Path, platform: FakePlatform) -> None:
    platform.agent_script = [{"status": "running"}, {"status": "completed", "reply": "Done."}]
    result = CliRunner().invoke(cli_module.app, ["chat", "--project", str(linked_repo)], input="go\n/quit\n")
    assert result.exit_code == 0, result.output
    assert result.output.count("Done.") == 1


def test_chat_says_so_when_the_reply_is_empty(linked_repo: Path, platform: FakePlatform) -> None:
    platform.agent_script = [{"status": "completed", "reply": ""}]
    result = CliRunner().invoke(cli_module.app, ["chat", "--project", str(linked_repo)], input="go\n/quit\n")
    assert result.exit_code == 0, result.output
    assert "finished without writing a reply" in result.output


def test_chat_with_a_specialist_on_a_chosen_model(linked_repo: Path, platform: FakePlatform) -> None:
    platform.agent_script = [
        {"status": "completed", "reply": "Three competitors."},
        {"status": "completed", "reply": "And a fourth."},
        {"status": "completed", "reply": "The team's view."},
    ]
    result = CliRunner().invoke(
        cli_module.app,
        ["chat", "--project", str(linked_repo), "--agent", "research", "--model", "google_genai:gemini-3.8-flash"],
        input="Who else does this?\nAny more?\n/agent auto\nWhat do we do?\n/quit\n",
    )
    assert result.exit_code == 0, result.output
    assert "Talking to the research agent on KUN (Kunemi) on the platform, on google_genai:gemini-3.8-flash" in result.output
    first, second, third = platform.runs_started
    assert first == {"message": "Who else does this?", "agent": "research", "model": "google_genai:gemini-3.8-flash"}
    # The conversation keeps its model: later messages don't send one.
    assert second == {"message": "Any more?", "thread_id": "thread-1", "agent": "research"}
    assert third == {"message": "What do we do?", "thread_id": "thread-1"}  # /agent auto


def test_chat_refuses_a_model_for_an_existing_conversation(linked_repo: Path, platform: FakePlatform) -> None:
    result = CliRunner().invoke(
        cli_module.app, ["chat", "--project", str(linked_repo), "--thread", "t1", "--model", "openai:x"]
    )
    assert result.exit_code != 0 and "keeps the model it started with" in result.output
    bad = CliRunner().invoke(cli_module.app, ["chat", "--project", str(linked_repo), "--agent", "Not a handle"])
    assert bad.exit_code != 0 and "use auto or an agent's handle" in bad.output


def test_chat_with_a_custom_agent_and_list_the_agents(linked_repo: Path, platform: FakePlatform) -> None:
    platform.agent_script = [{"status": "completed", "reply": "No secrets leaked."}]
    result = CliRunner().invoke(
        cli_module.app, ["chat", "--project", str(linked_repo), "--agent", "security"], input="Any leaks?\n/quit\n"
    )
    assert result.exit_code == 0, result.output
    assert platform.runs_started[0] == {"message": "Any leaks?", "agent": "security"}

    listed = CliRunner().invoke(cli_module.app, ["agents", "--project", str(linked_repo)])
    assert listed.exit_code == 0, listed.output
    assert "@research" in listed.output and "[built-in]" in listed.output
    assert "@security" in listed.output and "Security reviewer  [custom (this project)]" in listed.output
