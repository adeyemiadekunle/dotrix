"""`dotrix chat`'s work and approval modes, the runtime, thinking, Stop, Continue, and Build's handoff to Kai."""
from __future__ import annotations

import sys
from pathlib import Path

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent))

from fake_platform import FakePlatform, coding_session  # noqa: E402

from dotrix_cli import cli as cli_module  # noqa: E402
from dotrix_cli.agent_client import PlatformAgent  # noqa: E402
from dotrix_cli.sync import LinkState  # noqa: E402


def chat(repo: Path, text: str, *args: str):
    return CliRunner().invoke(cli_module.app, ["chat", "--project", str(repo), *args], input=text)


def test_modes_and_runtime_go_with_the_message(platform: FakePlatform, linked_repo: Path) -> None:
    platform.agent_script = [{"status": "completed", "reply": "A plan."}]
    result = chat(linked_repo, "plan it\n/quit\n", "--mode", "plan", "--approvals", "accept-edits", "--runtime", "fx")
    assert result.exit_code == 0, result.output
    assert platform.runs_started == [
        {"message": "plan it", "work_mode": "plan", "approval_mode": "accept_edits", "chat_runtime": "fx"}
    ]
    assert "Plan >" in result.output


def test_slash_commands_change_the_modes(platform: FakePlatform, linked_repo: Path) -> None:
    platform.agent_script = [{"status": "completed", "reply": "Ok."}]
    result = chat(linked_repo, "/mode build\n/approvals auto\nship it\n/mode nonsense\n/quit\n")
    assert result.exit_code == 0, result.output
    assert platform.runs_started == [{"message": "ship it", "work_mode": "build", "approval_mode": "auto"}]
    assert "Build mode." in result.output and "Approvals: Auto" in result.output
    assert "Use /mode discuss, plan, build or review." in result.output


def test_runtime_is_only_for_a_new_conversation(linked_repo: Path) -> None:
    result = chat(linked_repo, "/quit\n", "--thread", "t-1", "--runtime", "fx")
    assert result.exit_code != 0 and "keeps the runtime" in result.output


def test_bad_modes_are_refused(linked_repo: Path) -> None:
    assert chat(linked_repo, "", "--mode", "ship").exit_code != 0
    assert chat(linked_repo, "", "--approvals", "yolo").exit_code != 0


def test_thinking_is_shown_before_the_reply(platform: FakePlatform, linked_repo: Path) -> None:
    platform.agent_script = [{"status": "running"}, {"status": "completed", "reply": "Hello."}]
    platform.streams = [[("thinking", "Weighing "), ("thinking", "it."), ("text", "Hello.")]]
    result = chat(linked_repo, "hi\n/quit\n")
    assert result.exit_code == 0, result.output
    assert "Thinking: Weighing it." in result.output
    assert result.output.index("Weighing it.") < result.output.index("Hello.")


def test_reconnected_thinking_is_not_repeated(platform: FakePlatform, state: LinkState) -> None:
    platform.agent_script = [{"status": "running"}, {"status": "completed", "reply": "Hi"}]
    platform.streams = [[("thinking", "Weighing "), ("thinking_text", "Weighing it"), ("text", "Hi")]]
    thought: list[str] = []
    agent = PlatformAgent(platform.client(), state, sleep=lambda s: None)
    agent.wait(agent.start("hi"), on_text=lambda t, n: None, on_thinking=thought.append)
    assert "".join(thought) == "Weighing it"


def test_ctrl_c_stops_the_run_and_keeps_the_chat(platform: FakePlatform, linked_repo: Path, monkeypatch) -> None:
    platform.agent_script = [{"status": "running"}]

    def interrupted(self, run, decide, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr(PlatformAgent, "converse", interrupted)
    result = chat(linked_repo, "go\n/quit\n")
    assert result.exit_code == 0, result.output
    assert platform.stopped == ["run-1"] and "Stopped." in result.output
    assert "dotrix chat --thread thread-1" in result.output


def test_continue_after_a_model_limit(platform: FakePlatform, linked_repo: Path) -> None:
    platform.agent_script = [
        {"status": "failed", "error_kind": "model_limit", "error": "rate limited", "resumes_at": "2026-11-01T14:05:00Z"},
        {"status": "completed", "reply": "Picked up where it stopped."},
    ]
    result = chat(linked_repo, "go\n/continue\n/quit\n")
    assert result.exit_code == 0, result.output
    assert "stopped at its model's limit" in result.output and "/continue" in result.output
    assert {"continue": "run-1", "when_reset": False} in platform.runs_started
    assert "Picked up where it stopped." in result.output


def test_continue_later(platform: FakePlatform, linked_repo: Path) -> None:
    platform.agent_script = [
        {"status": "failed", "error_kind": "model_limit", "error": "rate limited", "resumes_at": "2026-11-01T14:05:00Z"},
    ]
    result = chat(linked_repo, "go\n/continue later\n/continue\n/quit\n")
    assert result.exit_code == 0, result.output
    assert {"continue": "run-1", "when_reset": True} in platform.runs_started
    assert "goes on once the limit resets" in result.output
    assert "Nothing to continue" in result.output  # it was already continued


def test_build_names_the_session_kai_started(platform: FakePlatform, linked_repo: Path) -> None:
    platform.agent_script = [{"status": "completed", "reply": "Handed KUN-7 to Kai."}]
    older = coding_session("KUN-3", session_id="0192aaaa-0000-7000-8000-000000000003", thread_id="thread-1")
    started = coding_session("KUN-7", thread_id="thread-1", status="awaiting_approval")
    elsewhere = coding_session("KUN-9", session_id="0192bbbb-0000-7000-8000-000000000009", thread_id="thread-2")
    platform.coding_session_lists = [[older, elsewhere], [older, started, elsewhere]]
    result = chat(linked_repo, "build it\n/quit\n", "--mode", "build", "--thread", "thread-1")
    assert result.exit_code == 0, result.output
    assert "Kai is on KUN-7 (Waiting for approval): dotrix codes show KUN-7" in result.output
    assert "KUN-3" not in result.output and "KUN-9" not in result.output
