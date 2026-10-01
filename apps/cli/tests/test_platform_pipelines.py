"""`pmagent triage` and `pmagent review`, and answering a checkpoint (the agent's plan before a
large job) inline."""
from __future__ import annotations

import sys
from pathlib import Path

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent))

from fake_platform import FakePlatform, approval  # noqa: E402

from pmagent_cli import cli as cli_module  # noqa: E402

PLAN = {"summary": "Three specialists, eight steps", "plan": ["Spec it", "Assess impact"]}


def invoke(repo: Path, *args: str, input: str | None = None):
    return CliRunner().invoke(cli_module.app, [*args, "--project", str(repo)], input=input)


def test_triage_sends_the_report_and_follows_the_run(linked_repo: Path, platform: FakePlatform) -> None:
    platform.agent_script = [{"status": "completed", "reply": "It duplicates KUN-4; I commented there."}]
    result = invoke(linked_repo, "triage", "Drivers see the wrong zone")
    assert result.exit_code == 0, result.output
    assert platform.bodies("/agent/triage") == [{"report": "Drivers see the wrong zone"}]
    assert "It duplicates KUN-4" in result.output


def test_triage_reads_the_report_from_stdin(linked_repo: Path, platform: FakePlatform) -> None:
    platform.agent_script = [{"status": "completed", "reply": "Created."}]
    result = invoke(linked_repo, "triage", input="Crash on login\nSince v2\n")
    assert result.exit_code == 0, result.output
    assert platform.bodies("/agent/triage") == [{"report": "Crash on login\nSince v2"}]


def test_review_asks_the_reviewer(linked_repo: Path, platform: FakePlatform) -> None:
    platform.agent_script = [{"status": "completed", "reply": "Send it back."}]
    result = invoke(linked_repo, "review", "kun-3")
    assert result.exit_code == 0, result.output
    assert any(r.url.path.endswith("/agent/issues/KUN-3/review") for r in platform.requests)
    assert "Send it back." in result.output


def test_changing_the_plan_at_a_checkpoint(linked_repo: Path, platform: FakePlatform) -> None:
    checkpoint = approval("c1", tool="checkpoint", target=None, args=PLAN)
    platform.agent_script = [
        {"status": "awaiting_approval", "approvals": [checkpoint]},
        {"status": "completed", "reply": "Just the spec, done.", "approvals": [checkpoint | {"status": "approved"}]},
    ]
    result = invoke(linked_repo, "run", "Plan the launch", input="h\nSkip the impact\n")
    assert result.exit_code == 0, result.output
    assert "1. Spec it" in result.output and "Three specialists, eight steps" in result.output
    [body] = platform.bodies("/decisions")
    assert body == {"decisions": [{"approval_id": "c1", "decision": "steer", "reason": "Skip the impact"}]}


def test_stopping_at_a_checkpoint(linked_repo: Path, platform: FakePlatform) -> None:
    checkpoint = approval("c1", tool="checkpoint", target=None, args=PLAN)
    platform.agent_script = [
        {"status": "awaiting_approval", "approvals": [checkpoint]},
        {"status": "completed", "reply": "Stopped.", "approvals": [checkpoint | {"status": "rejected"}]},
    ]
    result = invoke(linked_repo, "run", "Plan the launch", input="s\n")
    assert result.exit_code == 0, result.output
    assert platform.bodies("/decisions")[0]["decisions"][0]["decision"] == "reject"


def test_research_shows_claims_and_sources(linked_repo: Path, platform: FakePlatform) -> None:
    report = {"id": "o1", "agent": "research", "kind": "report", "actions": [], "note": None, "items": [
        {"index": 0, "state": "open", "data": {"claim": "VAT is 20%", "sources": ["S1"]},
         "check": {"status": "supported", "quotes": []}},
        {"index": 1, "state": "open", "data": {"claim": "It will rise", "sources": ["S2"]},
         "check": {"status": "unsupported", "quotes": []}},
        {"index": 2, "state": "dismissed", "data": {"claim": "Dropped"}, "check": None},
    ]}
    sources = [
        {"label": "S1", "url": "https://www.gov.uk/vat", "title": "VAT rates", "host": "gov.uk", "tier": "primary",
         "kind": "page", "flagged": []},
        {"label": "S2", "url": "https://blog.example/x", "title": "", "host": "blog.example", "tier": "other",
         "kind": "search", "flagged": ["addresses an AI"]},
    ]
    platform.agent_script = [{"status": "completed", "reply": "It's 20%.", "outputs": [report], "sources": sources}]
    result = invoke(linked_repo, "run", "What's the UK VAT rate?")
    assert result.exit_code == 0, result.output
    assert "Findings:\n  - VAT is 20% [S1] (supported)" in result.output
    assert "Assumptions (no quote found in the pages read):\n  - It will rise [S2]" in result.output
    assert "Dropped" not in result.output
    assert "[S1] VAT rates - gov.uk, primary, read" in result.output
    assert "[S2] https://blog.example/x - blog.example, other, search result  (addressed AI agents; ignored)" in result.output
