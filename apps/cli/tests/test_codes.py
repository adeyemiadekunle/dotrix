"""`dotrix codes`: Kai's coding sessions from the terminal, and `dotrix code --wait`."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent))

from fake_platform import FakePlatform, coding_run, coding_session  # noqa: E402

from dotrix_cli import cli as cli_module  # noqa: E402
from dotrix_cli import codes as codes_module  # noqa: E402

SID = "0192abcd-0000-7000-8000-000000000001"
EVENTS = [
    {"kind": "tool", "text": "Read src/lookup.py"},
    {"kind": "tool", "text": "Read tests/test_lookup.py"},
    {"kind": "tool", "text": "Ran pytest -q"},
    {"kind": "tool", "text": "Edited src/lookup.py"},
    {"kind": "text", "text": "Fixed it."},
]


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch) -> None:
    monkeypatch.setattr(codes_module, "sleep", lambda s: None)


def codes(repo: Path, *args: str):
    return CliRunner().invoke(cli_module.app, ["codes", *args, "--project", str(repo)])


def one_session(platform: FakePlatform, *turns: dict, **session: object) -> None:
    platform.coding_sessions = [coding_session(**session)]
    platform.coding_turns = {SID: list(turns)}


def test_list(platform: FakePlatform, linked_repo: Path) -> None:
    platform.coding_sessions = [
        coding_session(pr_number=12, pr_state="open", thread_id="thread-1"),
        coding_session("KUN-2", session_id="0192ffff-0000-7000-8000-000000000002", project_id="elsewhere"),
    ]
    result = codes(linked_repo)
    assert result.exit_code == 0, result.output
    assert "KUN-7" in result.output and "PR opened" in result.output and "PR #12 (open)" in result.output
    assert "from a conversation" in result.output
    assert "KUN-2" not in result.output  # another project's
    assert platform.requests[-1].url.params["archived"] == "exclude"
    assert codes(linked_repo, "--all").exit_code == 0
    assert platform.requests[-1].url.params["archived"] == "include"


def test_list_empty(platform: FakePlatform, linked_repo: Path) -> None:
    result = codes(linked_repo)
    assert result.exit_code == 0 and "no coding sessions" in result.output


def test_show(platform: FakePlatform, linked_repo: Path) -> None:
    pushed = coding_run(
        "run-1", note="Fix the lookup", events=EVENTS, summary="Fixed the lookup.", commit_sha="abc", pr_number=12,
        ci_state="passed", files_changed=[{"path": "src/lookup.py", "added": 4, "removed": 1}],
        diff="diff --git a/src/lookup.py b/src/lookup.py\n+fixed\n-broken\n",
    )
    one_session(platform, pushed, pr_number=12, pr_url="https://github.com/kunemi/app/pull/12", pr_state="open")
    result = codes(linked_repo, "show", "kun-7", "--diff")
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Turn 1" in out and "You: Fix the lookup" in out
    assert "Read 2 files, ran 1 command, edited 1 file" in out
    assert "Fixed the lookup." in out and "src/lookup.py  +4 −1" in out
    assert "Pull request #12 (open)  CI passed" in out
    assert "+fixed" in out and "-broken" in out


def test_show_by_session_id_and_unknown(platform: FakePlatform, linked_repo: Path) -> None:
    one_session(platform, coding_run("run-1"))
    assert codes(linked_repo, "show", "0192abcd").exit_code == 0
    missing = codes(linked_repo, "show", "KUN-99")
    assert missing.exit_code != 0 and "no session on KUN-99" in missing.output


def test_approve_and_reject(platform: FakePlatform, linked_repo: Path) -> None:
    one_session(platform, coding_run("run-1", status="awaiting_approval", can_decide=True))
    result = codes(linked_repo, "approve", "KUN-7")
    assert result.exit_code == 0, result.output
    assert platform.bodies("/run-1/decision") == [{"decision": "approve", "reason": None}]
    assert "queued" in result.output
    assert codes(linked_repo, "approve", "KUN-7").exit_code != 0  # nothing waits now

    one_session(platform, coding_run("run-1", status="awaiting_approval", can_decide=True))
    assert codes(linked_repo, "reject", "KUN-7", "--reason", "Not now").exit_code == 0
    assert platform.bodies("/run-1/decision")[-1] == {"decision": "reject", "reason": "Not now"}


def test_accept_and_discard(platform: FakePlatform, linked_repo: Path) -> None:
    one_session(platform, coding_run("run-1", status="changes_ready", can_decide=True))
    result = codes(linked_repo, "accept", "KUN-7")
    assert result.exit_code == 0 and "PR opened".lower() in result.output
    one_session(platform, coding_run("run-1", status="changes_ready", can_decide=True))
    assert codes(linked_repo, "discard", "KUN-7").exit_code == 0
    assert platform.bodies("/run-1/decision")[-1]["decision"] == "reject"


def test_discard_falls_back_to_stop(platform: FakePlatform, linked_repo: Path) -> None:
    one_session(platform, coding_run("run-1", status="changes_ready", can_decide=False, can_stop=True))
    assert codes(linked_repo, "discard", "KUN-7").exit_code == 0
    assert any(r.url.path.endswith("/run-1/stop") for r in platform.requests)
    assert not platform.bodies("/run-1/decision")


def test_follow_up_and_wait(platform: FakePlatform, linked_repo: Path) -> None:
    one_session(platform, coding_run("run-1"))
    platform.coding_script = [
        {"status": "running", "events": EVENTS[:2]},
        {"status": "pr_opened", "events": EVENTS, "summary": "Added the test."},
    ]
    result = CliRunner().invoke(
        cli_module.app,
        ["codes", "follow", "KUN-7", "Add a test", "--approvals", "auto", "--wait", "--project", str(linked_repo)],
    )
    assert result.exit_code == 0, result.output
    assert platform.bodies(f"/sessions/{SID}/turns") == [{"message": "Add a test", "approval_mode": "auto"}]
    assert "· Read src/lookup.py" in result.output and "· Ran pytest -q" in result.output
    assert result.output.count("Read src/lookup.py") == 1
    assert "Added the test." in result.output and "Turn 2" in result.output


def test_stop_revert_recover(platform: FakePlatform, linked_repo: Path) -> None:
    one_session(platform, coding_run("run-1", status="running", can_stop=True))
    assert codes(linked_repo, "stop", "KUN-7").exit_code == 0
    assert platform.coding_turns[SID][0]["status"] == "stopped"

    one_session(platform, coding_run("run-1", commit_sha="abc", can_revert=True), )
    result = codes(linked_repo, "revert", "KUN-7")
    assert result.exit_code == 0 and "Turn 2 reverts turn 1" in result.output
    assert codes(linked_repo, "revert", "KUN-7", "--turn", "2").exit_code != 0  # a revert isn't revertable

    one_session(platform, coding_run("run-1", status="recovery_required", can_recover=True))
    assert codes(linked_repo, "recover", "KUN-7", "--discard").exit_code == 0
    assert platform.bodies("/run-1/recover") == [{"action": "discard"}]


def test_code_with_wait(platform: FakePlatform, linked_repo: Path) -> None:
    platform.coding_turns = {SID: [coding_run("run-new", status="running")]}
    platform.coding_script = [{"status": "no_changes", "summary": "Nothing to change."}]
    result = CliRunner().invoke(
        cli_module.app,
        ["code", "KUN-7", "--cloud", "--approvals", "accept-edits", "--wait", "--project", str(linked_repo)],
    )
    assert result.exit_code == 0, result.output
    body = platform.bodies("/issues/KUN-7/runs")[0]
    assert body["approval_mode"] == "accept_edits" and body["location"] == "cloud"
    assert "is queued" in result.output and "Nothing to change." in result.output


def test_steps_summary() -> None:
    assert codes_module.steps_summary([]) == "Worked on it"
    assert codes_module.steps_summary([{"kind": "tool", "text": "Searched"}]) == "Used 1 other tool"
