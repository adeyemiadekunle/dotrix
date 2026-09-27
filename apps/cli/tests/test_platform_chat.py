"""`pmagent chat` and `brief` against the platform's agents, with inline approvals."""
from __future__ import annotations

import functools
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent))

from fake_platform import PID, WS, FakePlatform, approval  # noqa: E402

from pmagent_cli import cli as cli_module  # noqa: E402
from pmagent_cli.agent_client import PlatformAgent  # noqa: E402
from pmagent_cli.sync import LinkState  # noqa: E402
from pmagent_engine.config import ProjectConfig  # noqa: E402

DIFF = "--- a/pmagent/roadmap.md\n+++ b/pmagent/roadmap.md\n@@ -1 +1,2 @@\n # Roadmap\n+Phase 1: core\n"


@pytest.fixture
def platform() -> FakePlatform:
    return FakePlatform()


@pytest.fixture
def state() -> LinkState:
    return LinkState(api_url="http://fake", workspace_id=WS, project_id=PID, project_key="KUN", project_name="Kunemi")


def agent(platform: FakePlatform, state: LinkState) -> PlatformAgent:
    return PlatformAgent(platform.client(), state, sleep=lambda s: None)


# -- the approval loop -------------------------------------------------------------------


def test_converse_settles_each_pause(platform: FakePlatform, state: LinkState) -> None:
    platform.agent_script = [
        {"status": "running"},
        {"status": "awaiting_approval", "approvals": [approval("a1"), approval("a2", target="/pmagent/vision.md")]},
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


def test_person_without_approve_permission_leaves_it_waiting(platform: FakePlatform, state: LinkState) -> None:
    platform.agent_script = [{"status": "awaiting_approval", "approvals": [approval("a1")]}]
    platform.deny_decisions = True
    outcome = agent(platform, state).converse(agent(platform, state).start("x"), lambda *a: ("approve", None))
    assert outcome.left_waiting and outcome.status == "awaiting_approval"


# -- the commands ----------------------------------------------------------------------


@pytest.fixture
def linked_repo(tmp_path: Path, state: LinkState, platform: FakePlatform, monkeypatch) -> Path:
    config = ProjectConfig(name="Kunemi", root_dir=str(tmp_path))
    Path(config.pmagent_dir).mkdir()
    config.save()
    state.save(config.pmagent_dir)
    monkeypatch.setattr(cli_module.PlatformClient, "signed_in", classmethod(lambda cls, url=None, store=None: platform.client()))
    # Don't actually wait between polls.
    monkeypatch.setattr(cli_module, "PlatformAgent", functools.partial(PlatformAgent, sleep=lambda s: None))
    return tmp_path


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
    assert "The agents want to: write_file -> /pmagent/roadmap.md" in out
    assert "+Phase 1: core" in out
    assert "(1 change(s) approved, 0 rejected)" in out
    assert "Roadmap updated with Phase 1." in out
    assert "pmagent chat --thread thread-1" in out
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
    assert platform.requests[0].url.path.endswith("/agent/briefing")


def test_brief_reports_a_failed_run(linked_repo: Path, platform: FakePlatform) -> None:
    platform.agent_script = [{"status": "failed", "error": "No API key for anthropic:claude-sonnet-5"}]
    result = CliRunner().invoke(cli_module.app, ["brief", "--project", str(linked_repo)])
    assert result.exit_code == 1 and "No API key" in result.output
