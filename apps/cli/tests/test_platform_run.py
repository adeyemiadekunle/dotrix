"""`pmagent run` / `jobs` / `jobs-approve` / `jobs-stop` against the platform, and the live
activity line ("Reading roadmap.md…") while the PM works."""
from __future__ import annotations

import sys
from pathlib import Path

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent))

from fake_platform import FakePlatform, approval  # noqa: E402

from pmagent_cli import cli as cli_module  # noqa: E402

DIFF = "--- a/pmagent/roadmap.md\n+++ b/pmagent/roadmap.md\n@@ -1 +1,2 @@\n # Roadmap\n+Phase 1: core\n"


def invoke(repo: Path, *args: str, input: str | None = None):
    return CliRunner().invoke(cli_module.app, [*args, "--project", str(repo)], input=input)


# -- activity ------------------------------------------------------------------------------


def test_chat_shows_what_the_pm_is_doing(linked_repo: Path, platform: FakePlatform) -> None:
    platform.agent_script = [{"status": "completed", "reply": "Three phases."}]
    platform.streams = [[("activity", "Reading roadmap.md"), ("text", "Three phases.")]]
    result = invoke(linked_repo, "chat", input="summarise the roadmap\n/quit\n")
    assert result.exit_code == 0, result.output
    # Piped output (not a terminal): each activity on a dim line of its own, then the reply.
    assert "· Reading roadmap.md…" in result.output
    assert result.output.index("Reading roadmap.md") < result.output.index("Three phases.")
    assert result.output.count("Three phases.") == 1


def test_in_a_terminal_the_status_line_is_replaced(capsys) -> None:
    printer = cli_module._StreamPrinter(tty=True)
    printer.activity("Checking the board")
    printer.activity("Looking at KUN-5")
    printer("KUN-5 is blocked.", True)
    printer.finish_line()
    out = capsys.readouterr().out
    # The status line is redrawn in place (carriage return + erase line): drawn, cleared and
    # redrawn for the second label, then cleared before the reply's text.
    assert out.count("\r\x1b[2K") == 4
    assert "\n" not in out.split("KUN-5 is blocked.")[0].strip("\n")  # no stray lines between
    assert out.rstrip().endswith("KUN-5 is blocked.")


# -- pmagent run -----------------------------------------------------------------------------


def test_run_streams_the_reply_and_settles_approvals_inline(linked_repo: Path, platform: FakePlatform) -> None:
    platform.agent_script = [
        {"status": "awaiting_approval", "approvals": [approval("a1", diff=DIFF)]},
        {"status": "completed", "reply": "Roadmap updated.", "approvals": [approval("a1", diff=DIFF, status="approved")]},
    ]
    platform.streams = [[("activity", "Drafting a change to roadmap.md")], [("text", "Roadmap updated.")]]
    result = invoke(linked_repo, "run", "Add phase 1 to the roadmap", input="a\n")
    assert result.exit_code == 0, result.output
    assert platform.runs_started == [{"message": "Add phase 1 to the roadmap"}]
    assert "+Phase 1: core" in result.output and "(1 change(s) approved, 0 rejected)" in result.output
    assert result.output.count("Roadmap updated.") == 1
    assert "pmagent chat --thread thread-1" in result.output


def test_run_in_the_background_returns_at_once(linked_repo: Path, platform: FakePlatform) -> None:
    result = invoke(linked_repo, "run", "Plan the quarter", "--background")
    assert result.exit_code == 0, result.output
    assert "Started run run-1 (queued) on the platform." in result.output
    assert not [r for r in platform.requests if r.url.path.endswith("/stream")]  # nothing followed


def test_a_failed_run_exits_non_zero(linked_repo: Path, platform: FakePlatform) -> None:
    platform.agent_script = [{"status": "failed", "error": "No API key for anthropic:claude-sonnet-5"}]
    result = invoke(linked_repo, "run", "hello")
    assert result.exit_code == 1 and "No API key" in result.output


def test_run_continues_a_thread(linked_repo: Path, platform: FakePlatform) -> None:
    platform.agent_script = [{"status": "completed", "reply": "Sure."}]
    invoke(linked_repo, "run", "and the vision?", "--thread", "thread-7", "--background")
    assert platform.runs_started == [{"message": "and the vision?", "thread_id": "thread-7"}]


# -- pmagent jobs ----------------------------------------------------------------------------


def test_jobs_lists_the_projects_runs(linked_repo: Path, platform: FakePlatform) -> None:
    platform.runs_list = [
        {"id": "run-2", "status": "awaiting_approval", "title": "Update the roadmap", "message": "Update the roadmap",
         "approvals": [approval("a1"), approval("a2", status="approved")], "created_at": "2026-09-28T10:00:00Z"},
        {"id": "run-1", "status": "completed", "title": None, "message": "What's blocked?\nand why",
         "approvals": [], "created_at": "2026-09-27T10:00:00Z"},
    ]
    result = invoke(linked_repo, "jobs")
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0].startswith("run-2  [awaiting_approval (1 change(s) to decide)]  Update the roadmap")
    assert lines[1].startswith("run-1  [completed]  What's blocked?  ")  # the first line of the message
    assert "ago" in lines[1]
    platform.runs_list = []
    assert "No runs yet" in invoke(linked_repo, "jobs").output


# -- pmagent jobs-approve / jobs-stop ---------------------------------------------------------


def test_jobs_approve_decides_everything_waiting(linked_repo: Path, platform: FakePlatform) -> None:
    platform.agent_script = [
        {"status": "awaiting_approval", "approvals": [approval("a1", diff=DIFF), approval("a2")]},
        {"status": "queued"},  # after the decisions
    ]
    result = invoke(linked_repo, "jobs-approve", "run-1")
    assert result.exit_code == 0, result.output
    assert "+Phase 1: core" in result.output  # what's being approved is shown
    assert platform.bodies("/decisions")[0]["decisions"] == [
        {"approval_id": "a1", "decision": "approve", "reason": None},
        {"approval_id": "a2", "decision": "approve", "reason": None},
    ]
    assert "Approved 2 change(s). Run run-1 -> queued" in result.output


def test_jobs_approve_can_reject_with_a_reason_and_follow(linked_repo: Path, platform: FakePlatform) -> None:
    platform.agent_script = [
        {"status": "awaiting_approval", "approvals": [approval("a1")]},
        {"status": "queued"},
        {"status": "completed", "reply": "OK, left it as it is."},
    ]
    result = invoke(linked_repo, "jobs-approve", "run-1", "--reject", "-m", "Not now", "--foreground")
    assert result.exit_code == 0, result.output
    assert platform.bodies("/decisions")[0]["decisions"] == [
        {"approval_id": "a1", "decision": "reject", "reason": "Not now"}
    ]
    assert "OK, left it as it is." in result.output


def test_jobs_approve_refuses_a_run_that_isnt_waiting(linked_repo: Path, platform: FakePlatform) -> None:
    platform.agent_script = [{"status": "completed", "reply": "Done."}]
    result = invoke(linked_repo, "jobs-approve", "run-1")
    assert result.exit_code == 1 and "isn't waiting for a decision (it's completed)" in result.output
    assert platform.bodies("/decisions") == []


def test_jobs_approve_without_permission(linked_repo: Path, platform: FakePlatform) -> None:
    platform.agent_script = [{"status": "awaiting_approval", "approvals": [approval("a1")]}]
    platform.deny_decisions = True
    result = invoke(linked_repo, "jobs-approve", "run-1")
    assert result.exit_code == 1 and "Your role can't decide this" in result.output


def test_jobs_stop(linked_repo: Path, platform: FakePlatform) -> None:
    result = invoke(linked_repo, "jobs-stop", "run-9")
    assert result.exit_code == 0, result.output
    assert platform.stopped == ["run-9"]
    assert "Run run-9 -> failed: Stopped by Ada" in result.output
