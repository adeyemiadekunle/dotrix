"""Coding runs (step 5c): asked for, approved, run in a sandbox, pushed to a new branch, and
opened as a PR. GitHub's API is faked (conftest.FakeGitHub), the repo is a local git repo, and the
"sandbox" is the local one with a scripted Claude Code in place of the real CLI."""
import asyncio
import base64
import dataclasses
import json
import subprocess
import uuid
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from dotrix_backend.modules.coding.runner import SHOTS_LIST, CodingWorker
from dotrix_backend.modules.coding.sandbox import ExecResult, LocalSandbox, LocalSession
from dotrix_backend.modules.coding.warm import WarmPool
from dotrix_backend.modules.connectors.github_app import get_github_app


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


class ScriptedClaude:
    """Stands in for `claude -p`: makes `edits` in the repo and prints stream-json events."""

    def __init__(self) -> None:
        self.edits: dict[str, str] = {}
        self.result = "Added refunds to the payment provider and a test; pytest passes."
        self.briefs: list[str] = []
        self.argv: list[str] = []
        self.env: dict[str, str] = {}

    def lines(self) -> list[str]:
        events: list[dict[str, Any]] = [{"type": "system", "subtype": "init", "model": "claude-test"}]
        for path in self.edits:
            events.append({"type": "assistant", "message": {"id": f"m-{path}", "content": [
                {"type": "text", "text": f"Editing {path}"},
                {"type": "tool_use", "name": "Edit", "input": {"file_path": f"/sandbox/repo/{path}"}},
            ], "usage": {"input_tokens": 1000, "output_tokens": 200}}})
        events.append({"type": "result", "subtype": "success", "result": self.result, "total_cost_usd": 0.12,
                       "usage": {"input_tokens": 1000 * len(self.edits), "output_tokens": 200 * len(self.edits)}})
        return [json.dumps(e) + "\n" for e in events]


class ScriptedSession(LocalSession):
    def __init__(self, root: Path, env: dict[str, str], agent: ScriptedClaude) -> None:
        super().__init__(root, env)
        self.agent = agent

    async def exec(self, argv, *, stdin=None, on_line=None, timeout, cancel=None) -> ExecResult:
        if argv[0] != "claude":
            return await super().exec(argv, stdin=stdin, on_line=on_line, timeout=timeout, cancel=cancel)
        self.agent.argv, self.agent.env = argv, dict(self.env)
        self.agent.briefs.append((stdin or b"").decode())
        for path, text in self.agent.edits.items():
            target = self.root / "repo" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        for line in self.agent.lines():
            assert on_line is not None
            await on_line(line)
        return ExecResult(code=0, stdout="", stderr="")


class ScriptedSandbox(LocalSandbox):
    def __init__(self, agent: ScriptedClaude) -> None:
        self.agent = agent
        self.opened = 0

    async def open(self, run_id, source, tool, model_key):
        self.opened += 1
        session = await super().open(run_id, source, tool, model_key)
        assert isinstance(session, LocalSession)
        return ScriptedSession(session.root, session.env, self.agent)


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    """kunemi/api on "GitHub"."""
    root = tmp_path / "origin"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "src").mkdir()
    (root / "src/payments.py").write_text("class PaymentProvider:\n    pass\n")
    _git(root, "add", "-A")
    _git(root, "-c", "user.email=a@b.c", "-c", "user.name=A", "commit", "-qm", "first")
    _git(root, "config", "receive.denyCurrentBranch", "refuse")
    return root


@pytest.fixture
def claude() -> ScriptedClaude:
    return ScriptedClaude()


@pytest.fixture
async def coding(db_client: AsyncClient, github, github_world, origin: Path, claude: ScriptedClaude):
    """Ada (owner) and Cat (member); KUN connected to kunemi/api; coding on, with Claude Code."""
    app = db_client._transport.app  # type: ignore[attr-defined]
    settings = app.state.settings
    client = app.dependency_overrides[get_github_app]()
    settings.coding_sandbox = "local"
    settings.anthropic_api_key = SecretStr("sk-ant-test")
    settings.github_app_id, settings.github_app_slug = "4242", "dotrix-test"
    settings.github_app_private_key = SecretStr(client.private_key)
    ada, cat, ws, kun, mob = await github_world()
    installation = (await db_client.post(f"{ws}/github/installations", json={"installation_id": 111, "code": "code-1"},
                                          headers=ada.headers)).json()
    connected = await db_client.put(f"{ws}/projects/{kun['id']}/repository",
                                    json={"installation_ref": installation["id"], "github_repo_id": 9001},
                                    headers=ada.headers)
    assert connected.status_code == 200, connected.text

    async def repo_url(ref) -> str:
        assert ref.full_name == "kunemi/api" and ref.default_branch == "main"
        return str(origin)

    sandbox = ScriptedSandbox(claude)
    jobs = app.state.jobs
    jobs.ctx = dataclasses.replace(jobs.ctx, coding=CodingWorker(
        jobs.ctx.session_factory, settings, sandbox, client, repo_url=repo_url, reviewer=app.state.runner,
        pool=WarmPool(3600, 0),  # each turn starts fresh here; the warm sandbox has a test of its own
    ))
    yield ada, cat, ws, kun, mob, sandbox


async def test_an_approved_run_opens_a_pr_on_a_new_branch(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude, agent_script
) -> None:
    ada, cat, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    await db_client.put(f"{base}/knowledge/files/requirements/refunds.md", headers=ada.headers,
                        json={"content": "# Refunds\n\nRefund within a week of purchase.\n"})
    story = (await db_client.post(f"{base}/issues", headers=ada.headers, json={
        "type": "story", "title": "Refund a payment",
        "description": "Implements requirements/refunds.md.\n\nAcceptance: refund() returns the amount.",
    })).json()

    availability = (await db_client.get(f"{base}/coding", headers=cat.headers)).json()
    assert availability == {"available": True, "agent": "claude-code", "sandbox": "local", "reason": None}
    # Members can't instruct the coding agent unless the workspace lets them.
    assert (await db_client.post(f"{base}/coding/issues/{story['key']}/runs", json={},
                                 headers=cat.headers)).status_code == 403

    started = await db_client.post(f"{base}/coding/issues/{story['key']}/runs", headers=ada.headers,
                                   json={"note": "Keep it small."})
    assert started.status_code == 201, started.text
    run = started.json()
    assert run["status"] == "awaiting_approval" and run["agent"] == "claude-code" and run["can_decide"]
    assert "Acceptance: refund() returns the amount." in run["brief"] and "Keep it small." in run["brief"]
    assert "Refund within a week of purchase." in run["brief"]  # the requirement it implements, as data
    again = await db_client.post(f"{base}/coding/issues/{story['key']}/runs", json={}, headers=ada.headers)
    assert again.status_code == 409 and again.json()["type"].endswith("/coding_busy")
    # Cat sees it, can't decide it.
    seen = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=cat.headers)).json()
    assert not seen["can_decide"] and seen["input_tokens"] is None
    assert (await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"},
                                 headers=cat.headers)).status_code == 403

    claude.edits = {
        "src/payments.py": "class PaymentProvider:\n    def refund(self, amount):\n        return amount\n",
        "tests/test_refund.py": "def test_refund():\n    assert True\n",
    }
    agent_script.say("Looks right: refund() returns the amount, and there's a test. Ready to merge.")
    done = await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"},
                                headers=ada.headers)
    assert done.status_code == 200, done.text
    run = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert run["status"] == "pr_opened", run
    assert run["pr_number"] == 1 and run["pr_url"] == "https://github.com/kunemi/api/pull/1"
    assert run["branch"].startswith(f"dotrix/{story['key'].lower()}-refund-a-payment-")
    assert {f["path"] for f in run["files_changed"]} == {"src/payments.py", "tests/test_refund.py"}
    assert run["summary"].startswith("Added refunds") and run["input_tokens"] == 2000 and run["cost_usd"] == 0.12
    assert "Edited src/payments.py" in [e["text"] for e in run["events"]]

    # The branch is on the remote with the agent's change; the default branch is untouched.
    assert _git(origin, "show", f"{run['branch']}:src/payments.py").endswith("return amount")
    assert _git(origin, "rev-parse", "main") == run["base_sha"] != run["commit_sha"]
    assert _git(origin, "rev-parse", run["branch"]) == run["commit_sha"]
    [pr] = github.pulls
    assert pr["head"] == run["branch"] and pr["base"] == "main" and pr["title"] == f"{story['key']}: Refund a payment"
    # The token was for this repo only, with push and PR rights; the agent never had it.
    assert github.token_requests[-1] == {"repository_ids": [9001], "permissions": {
        "metadata": "read", "contents": "write", "pull_requests": "write"}}
    assert set(claude.env) - {"ANTHROPIC_BASE_URL"} == {"PATH", "HOME", "LANG", "ANTHROPIC_API_KEY"} and claude.env["ANTHROPIC_API_KEY"] == "sk-ant-test"
    assert claude.argv[:3] == ["claude", "-p", "--bare"] and "--dangerously-skip-permissions" not in claude.argv

    # The issue is the coding tool's, in review, with the PR linked; a person closes it.
    issue = (await db_client.get(f"{base}/issues/{story['key']}", headers=ada.headers)).json()
    assert issue["status"] == "review" and issue["assignee_agent"] == "claude-code"
    assert {"kind": "pr", "url": run["pr_url"], "title": "PR #1: Refund a payment"} in issue["links"]

    # The Reviewer read the PR in a conversation of its own.
    review = (await db_client.get(f"{base}/agent/runs/{run['review_run_id']}", headers=ada.headers)).json()
    assert review["status"] == "completed" and review["reply"].startswith("Looks right")
    assert "src/payments.py (+2 -1)" in review["message"] and "<repo_content" in review["message"]

    actions = [e["action"] for e in (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()]
    assert {"coding.requested", "coding.approved", "coding.pr_opened"} <= set(actions)


async def test_changes_to_dotrix_or_workflows_are_never_pushed(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude
) -> None:
    ada, _, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Tidy"}, headers=ada.headers)).json()
    claude.edits = {"src/payments.py": "# tidy\n", ".dotrix/requirements/x.md": "# sneaky\n"}
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"}, headers=ada.headers)
    run = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert run["status"] == "failed" and ".dotrix/ stays on the platform" in run["error"]
    assert run["branch"] is None and github.pulls == []
    assert _git(origin, "branch", "--list", "dotrix/*") == ""

    # Workflows likewise; and a run that changes nothing ends without a PR.
    claude.edits = {".github/workflows/ci.yml": "on: push\n"}
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"}, headers=ada.headers)
    run = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert run["status"] == "failed" and "CI workflows" in run["error"]
    claude.edits = {}
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"}, headers=ada.headers)
    run = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert run["status"] == "no_changes" and github.pulls == []


async def test_rejecting_stopping_and_when_it_isnt_available(
    db_client: AsyncClient, coding, add_member
) -> None:
    ada, cat, ws, kun, mob, sandbox = coding
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Tidy"}, headers=ada.headers)).json()
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    rejected = await db_client.post(f"{base}/coding/runs/{run['id']}/decision",
                                    json={"decision": "reject", "reason": "Not yet"}, headers=ada.headers)
    assert rejected.json()["status"] == "rejected" and rejected.json()["decision_reason"] == "Not yet"
    assert (await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"},
                                 headers=ada.headers)).status_code == 409

    # Stopped before it starts: whoever asked (Cat, once the workspace lets members code), or an owner.
    await db_client.patch(ws, json={"member_permissions": ["agents:code"]}, headers=ada.headers)
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=cat.headers)).json()
    assert run["can_stop"] and not run["can_decide"]
    stopped = (await db_client.post(f"{base}/coding/runs/{run['id']}/stop", headers=cat.headers)).json()
    assert stopped["status"] == "stopped" and sandbox.opened == 0
    assert (await db_client.post(f"{base}/coding/runs/{run['id']}/stop", headers=cat.headers)).status_code == 409
    assert [r["status"] for r in (await db_client.get(f"{base}/coding/runs", params={"issue": task["key"]},
                                                       headers=cat.headers)).json()] == ["stopped", "rejected"]

    # MOB has no connected repo; epics are too big; nothing runs without a model key.
    mob_task = (await db_client.post(f"{ws}/projects/{mob['id']}/issues", json={"type": "task", "title": "x"},
                                     headers=ada.headers)).json()
    refused = await db_client.post(f"{ws}/projects/{mob['id']}/coding/issues/{mob_task['key']}/runs", json={},
                                   headers=ada.headers)
    assert refused.status_code == 409 and refused.json()["type"].endswith("/coding_unavailable")
    epic = (await db_client.post(f"{base}/issues", json={"type": "epic", "title": "Big"}, headers=ada.headers)).json()
    assert (await db_client.post(f"{base}/coding/issues/{epic['key']}/runs", json={},
                                 headers=ada.headers)).status_code == 422
    app = db_client._transport.app  # type: ignore[attr-defined]
    app.state.settings.anthropic_api_key = None
    reason = (await db_client.get(f"{base}/coding", headers=ada.headers)).json()["reason"]
    assert "Anthropic key" in reason


async def test_a_running_agent_is_stopped_and_nothing_is_pushed(
    db_client: AsyncClient, coding, github, claude: ScriptedClaude, monkeypatch
) -> None:
    """The worker polls for Stop while the agent works, and kills it."""
    from dotrix_backend.modules.coding import runner as runner_module

    ada, _, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    monkeypatch.setattr(runner_module, "STOP_POLL_SECONDS", 0.05)
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Slow"}, headers=ada.headers)).json()
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    pressed = asyncio.Event()

    async def stop_requested(self, run_id) -> bool:  # someone pressed Stop while it worked
        return pressed.is_set()

    async def slow_exec(self, argv, *, stdin=None, on_line=None, timeout, cancel=None):
        if argv[0] != "claude":
            return await LocalSession.exec(self, argv, stdin=stdin, on_line=on_line, timeout=timeout, cancel=cancel)
        pressed.set()
        assert cancel is not None
        await asyncio.wait_for(cancel.wait(), 5)
        return ExecResult(code=None, stdout="", stderr="", cancelled=True)

    monkeypatch.setattr(CodingWorker, "stop_requested", stop_requested)
    monkeypatch.setattr(ScriptedSession, "exec", slow_exec)
    await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"}, headers=ada.headers)
    run = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert run["status"] == "stopped" and run["error"] == "Stopped by a person" and github.pulls == []


async def _approve(db_client: AsyncClient, base: str, run: dict, headers: dict) -> dict:
    res = await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"}, headers=headers)
    assert res.status_code == 200, res.text
    return (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=headers)).json()


async def test_a_session_continues_on_its_branch_and_pr(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude, agent_script
) -> None:
    ada, cat, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Refunds"}, headers=ada.headers)).json()
    claude.edits = {"src/refunds.py": "def refund(amount):\n    return amount\n"}
    agent_script.say("Fine.", "Fine again.")
    first = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    assert first["session_id"] == first["id"] and first["turn"] == 1 and first["origin"] == "start"
    first = await _approve(db_client, base, first, ada.headers)
    assert first["status"] == "pr_opened" and first["pr_state"] == "open"

    # A follow-up: the same agent, told what was done so far, on the same branch and PR.
    claude.result = "Refunds over £500 now need a manager."
    claude.edits = {"src/refunds.py": "def refund(amount):\n    if amount > 500:\n        raise PermissionError\n    return amount\n"}
    turns = f"{base}/coding/sessions/{first['session_id']}/turns"
    assert (await db_client.post(turns, json={"message": "Large refunds"}, headers=cat.headers)).status_code == 403
    second = await db_client.post(turns, json={"message": "Refunds over £500 need a manager"}, headers=ada.headers)
    assert second.status_code == 201, second.text
    second = second.json()
    assert (second["turn"], second["origin"], second["session_id"]) == (2, "follow_up", first["session_id"])
    assert second["branch"] == first["branch"] and second["pr_number"] == first["pr_number"]
    assert "## Earlier in this session" in second["brief"] and "Added refunds" in second["brief"]
    assert "## What to do in this turn" in second["brief"] and "over £500 need a manager" in second["brief"]
    assert (await db_client.post(turns, json={"message": "more"}, headers=ada.headers)).status_code == 409  # one waits

    second = await _approve(db_client, base, second, ada.headers)
    assert second["status"] == "pr_opened" and second["pr_number"] == first["pr_number"]
    assert len(github.pulls) == 1  # no second PR: the branch moved on
    assert _git(origin, "rev-parse", f"{first['branch']}~1") == first["commit_sha"]
    assert "PermissionError" in _git(origin, "show", f"{first['branch']}:src/refunds.py")
    assert second["base_sha"] == first["commit_sha"]  # it started from the branch, not main
    issue = (await db_client.get(f"{base}/issues/{task['key']}", headers=ada.headers)).json()
    assert [link["url"] for link in issue["links"]].count(first["pr_url"]) == 1
    assert any("Pushed turn 2 to PR #1" in (e.get("body") or "") for e in issue["log"])

    # The session's turns, and the workspace's sessions (Chat's Coding tab).
    listed = (await db_client.get(f"{base}/coding/sessions/{first['session_id']}", headers=cat.headers)).json()
    assert [t["turn"] for t in listed] == [1, 2]
    [session] = (await db_client.get(f"{ws}/coding/sessions", headers=cat.headers)).json()
    assert session["session_id"] == first["session_id"] and session["turns"] == 2 and session["project_key"] == "KUN"
    assert session["issue_title"] == "Refunds" and session["status"] == "pr_opened" and session["pr_number"] == 1


async def test_assigning_to_a_coding_tool_starts_a_session_and_approvers_are_told(
    db_client: AsyncClient, coding
) -> None:
    ada, cat, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Export"}, headers=ada.headers)).json()

    # Cat may assign Claude Code, but may not instruct the coding agent: no session.
    await db_client.patch(f"{base}/issues/{task['key']}", json={"assignee_agent": "claude-code"}, headers=cat.headers)
    assert (await db_client.get(f"{base}/coding/runs", headers=ada.headers)).json() == []

    # Once the workspace lets members code, assigning starts one in the background.
    await db_client.patch(f"{base}/issues/{task['key']}", json={"assignee_agent": None}, headers=ada.headers)
    await db_client.patch(ws, json={"member_permissions": ["agents:code"]}, headers=ada.headers)
    await db_client.patch(f"{base}/issues/{task['key']}", json={"assignee_agent": "claude-code"}, headers=cat.headers)
    [run] = (await db_client.get(f"{base}/coding/runs", headers=ada.headers)).json()
    assert run["origin"] == "assigned" and run["status"] == "awaiting_approval"
    # Creating an issue assigned to a coding tool does the same.
    other = (await db_client.post(f"{base}/issues", headers=cat.headers,
                                  json={"type": "task", "title": "Import", "assignee_agent": "codex"})).json()
    assert [r["origin"] for r in (await db_client.get(f"{base}/coding/runs", params={"issue": other["key"]},
                                                       headers=ada.headers)).json()] == ["assigned"]

    # Ada (who may approve) is told; it counts until decided, and Cat hears the decision.
    notes = (await db_client.get(f"{ws}/notifications", params={"kind": "approval"}, headers=ada.headers)).json()
    waiting = next(n for n in notes if n["coding_run_id"] == run["id"])
    assert waiting["title"] == f"Coding {task['key']}: Export" and not waiting["resolved"]
    assert waiting["coding_session_id"] == run["session_id"] and waiting["issue_key"] == task["key"]
    assert (await db_client.get(f"{ws}/notifications/counts", headers=ada.headers)).json()["by_kind"]["approval"] == 2
    await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "reject", "reason": "Later"},
                         headers=ada.headers)
    notes = (await db_client.get(f"{ws}/notifications", params={"kind": "approval"}, headers=ada.headers)).json()
    assert next(n for n in notes if n["coding_run_id"] == run["id"])["resolved"]
    [decided] = (await db_client.get(f"{ws}/notifications", params={"kind": "decided"}, headers=cat.headers)).json()
    assert decided["title"] == f"1 rejected: Coding {task['key']}: Export" and decided["excerpt"] == "Later"


async def test_a_merged_pr_is_recorded_on_the_session_and_the_issue(
    db_client: AsyncClient, coding, github, claude: ScriptedClaude, agent_script, deliver
) -> None:
    ada, _, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Ship"}, headers=ada.headers)).json()
    claude.edits = {"src/ship.py": "SHIP = True\n"}
    agent_script.say("Fine.")
    run = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    run = await _approve(db_client, base, run, ada.headers)
    payload = {"action": "closed", "pull_request": {"number": run["pr_number"], "merged": True},
               "repository": {"id": 9001, "full_name": "kunemi/api"}}
    assert (await deliver("pull_request", payload)).status_code == 202
    run = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert run["pr_state"] == "merged"
    issue = (await db_client.get(f"{base}/issues/{task['key']}", headers=ada.headers)).json()
    assert issue["status"] == "review"  # a person closes it
    assert any(e.get("body") == f"PR #{run['pr_number']} was merged on GitHub" for e in issue["log"])

    # The session stays open: more work starts from the default branch, on a new branch and PR.
    [listed] = (await db_client.get(f"{ws}/coding/sessions", headers=ada.headers)).json()
    assert listed["state"] != "closed"
    agent_script.say("Fine again.")
    claude.edits = {"src/ship.py": "SHIP = True\nVERSION = 2\n"}
    turns = f"{base}/coding/sessions/{run['session_id']}/turns"
    more = (await db_client.post(turns, json={"message": "Add a version"}, headers=ada.headers)).json()
    assert more["branch"] is None and more["pr_number"] is None
    more = await _approve(db_client, base, more, ada.headers)
    assert more["status"] == "pr_opened", more.get("error")
    assert more["branch"] != run["branch"] and more["pr_number"] != run["pr_number"]
    assert len(github.pulls) == 2 and github.pulls[-1]["base"] == "main"


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


class ShootingSession(ScriptedSession):
    """A sandbox where the agent's browser left a screenshot, a copy of it, and a file that only looks like one."""

    async def exec(self, argv, *, stdin=None, on_line=None, timeout, cancel=None) -> ExecResult:
        if argv[:2] == ["sh", "-c"] and argv[2] == SHOTS_LIST:
            return ExecResult(code=0, stdout="/tmp/playwright/page-subtract.png\n/tmp/page-subtract.png\n/tmp/notes.png\n", stderr="")
        if argv[:2] == ["sh", "-c"] and "base64 -w0" in argv[2]:
            data = PNG if "page-subtract.png" in argv[2] else b"not an image at all"
            return ExecResult(code=0, stdout=base64.b64encode(data).decode(), stderr="")
        return await super().exec(argv, stdin=stdin, on_line=on_line, timeout=timeout, cancel=cancel)


class ShootingSandbox(ScriptedSandbox):
    kind = "docker"  # screenshots are kept from the coding image's sandboxes, never the local one

    async def open(self, run_id, source, tool, model_key):
        session = await super().open(run_id, source, tool, model_key)
        return ShootingSession(session.root, session.env, self.agent)


async def test_the_agent_s_screenshots_are_kept_and_shown(
    db_client: AsyncClient, coding, claude: ScriptedClaude, agent_script, storage
) -> None:
    ada, cat, ws, kun, _, _ = coding
    app = db_client._transport.app  # type: ignore[attr-defined]
    jobs = app.state.jobs
    jobs.ctx = dataclasses.replace(jobs.ctx, coding=dataclasses.replace(jobs.ctx.coding, sandbox=ShootingSandbox(claude), storage=storage))
    base = f"{ws}/projects/{kun['id']}"
    issue = (await db_client.post(f"{base}/issues", headers=ada.headers, json={"title": "Add a Subtract button"})).json()
    run = (await db_client.post(f"{base}/coding/issues/{issue['key']}/runs", json={}, headers=ada.headers)).json()
    claude.edits = {"src/payments.py": "class PaymentProvider:\n    def subtract(self): ...\n"}
    agent_script.say("Looks right.")
    done = await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"}, headers=ada.headers)
    assert done.status_code == 200, done.text
    run = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=cat.headers)).json()
    assert run["status"] == "pr_opened", run.get("error")
    # Images only, whatever the name says, and each once; listed on the run, served to anyone who sees the project.
    assert run["screenshots"] == [{"index": 0, "name": "page-subtract.png", "size": len(PNG), "content_type": "image/png"}]
    assert any(e["text"] == "Kept 1 screenshot from the browser" for e in run["events"])
    shot = await db_client.get(f"{base}/coding/runs/{run['id']}/screenshots/0", headers=cat.headers)
    assert shot.status_code == 200 and shot.content == PNG and shot.headers["content-type"] == "image/png"
    assert (await db_client.get(f"{base}/coding/runs/{run['id']}/screenshots/1", headers=cat.headers)).status_code == 404


async def test_every_event_is_kept_and_read_a_page_at_a_time(
    db_client: AsyncClient, coding, claude: ScriptedClaude, agent_script
) -> None:
    """The run keeps its latest 300 events for quick reads; coding_events keeps every one, in order."""
    ada, cat, ws, kun, _, _ = coding
    app = db_client._transport.app  # type: ignore[attr-defined]
    worker = app.state.jobs.ctx.coding
    base = f"{ws}/projects/{kun['id']}"
    issue = (await db_client.post(f"{base}/issues", headers=ada.headers, json={"title": "Tidy payments"})).json()
    run = (await db_client.post(f"{base}/coding/issues/{issue['key']}/runs", json={}, headers=ada.headers)).json()
    claude.edits = {"src/payments.py": "# tidy\n"}
    agent_script.say("Fine.")
    assert (await db_client.post(f"{base}/coding/runs/{run['id']}/decision", json={"decision": "approve"},
                                 headers=ada.headers)).status_code == 200
    before = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=cat.headers)).json()["event_count"]
    await worker._update(uuid.UUID(run["id"]), events=[{"at": "2026-10-10T12:00:00+00:00", "kind": "tool", "text": f"Step {i}"} for i in range(350)])

    read = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=cat.headers)).json()
    assert read["event_count"] == before + 350 and len(read["events"]) == 300 and read["events"][-1]["text"] == "Step 349"
    first = (await db_client.get(f"{base}/coding/runs/{run['id']}/events", params={"limit": 100}, headers=cat.headers)).json()
    assert [e["seq"] for e in first["events"]] == list(range(100)) and first["next"] == 99
    seen, after = list(first["events"]), first["next"]
    while after is not None:
        page = (await db_client.get(f"{base}/coding/runs/{run['id']}/events", params={"after": after, "limit": 1000},
                                    headers=cat.headers)).json()
        seen += page["events"]
        after = page["next"]
    assert len(seen) == before + 350 and [e["seq"] for e in seen] == list(range(before + 350))
    assert seen[before]["text"] == "Step 0" and seen[-1]["text"] == "Step 349"


class TranscriptSession(ScriptedSession):
    """Claude Code keeps its conversation under ~/.claude: this one writes a transcript there, and
    notes whether one was already there when a turn started (a warm sandbox, or one restored)."""

    async def exec(self, argv, *, stdin=None, on_line=None, timeout, cancel=None) -> ExecResult:
        if argv[0] == "claude":
            transcript = Path(self.env["HOME"]) / ".claude" / "projects" / "-repo" / "conversation.jsonl"
            self.agent.found_transcript.append(transcript.read_text() if transcript.exists() else None)
            transcript.parent.mkdir(parents=True, exist_ok=True)
            transcript.write_text((transcript.read_text() if transcript.exists() else "") + f"turn {len(self.agent.found_transcript)}\n")
            self.agent.argvs.append(list(argv))
        return await super().exec(argv, stdin=stdin, on_line=on_line, timeout=timeout, cancel=cancel)


class TranscriptSandbox(ScriptedSandbox):
    async def open(self, run_id, source, tool, model_key):
        session = await super().open(run_id, source, tool, model_key)
        return TranscriptSession(session.root, session.env, self.agent)


async def test_a_session_keeps_its_sandbox_and_resumes_its_conversation(
    db_client: AsyncClient, coding, github, claude: ScriptedClaude, agent_script, storage
) -> None:
    """Phase B: a follow-up runs in the sandbox the last turn left (warm), resuming Claude Code's
    conversation; after a restart a fresh sandbox gets the saved transcript and still resumes; closing
    the session drops the sandbox and the transcript."""
    from cryptography.fernet import Fernet

    from dotrix_backend.core.crypto import Secrets

    ada, _, ws, kun, _, _ = coding
    app = db_client._transport.app  # type: ignore[attr-defined]
    jobs = app.state.jobs
    sandbox = TranscriptSandbox(claude)
    worker = dataclasses.replace(jobs.ctx.coding, sandbox=sandbox, storage=storage,
                                 secrets=Secrets(Fernet.generate_key().decode()), pool=WarmPool(3600, 3))
    jobs.ctx = dataclasses.replace(jobs.ctx, coding=worker)
    claude.found_transcript, claude.argvs = [], []
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Refunds"}, headers=ada.headers)).json()
    agent_script.say("Fine.", "Fine again.", "And again.")

    # Turn 1: a fresh sandbox, a new conversation; the sandbox stays up, the transcript is saved.
    claude.edits = {"src/refunds.py": "def refund(amount):\n    return amount\n"}
    first = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    first = await _approve(db_client, base, first, ada.headers)
    assert first["status"] == "pr_opened" and sandbox.opened == 1
    session_id = first["session_id"]
    conversation = claude.argvs[0][claude.argvs[0].index("--session-id") + 1]
    [listed] = (await db_client.get(f"{ws}/coding/sessions", headers=ada.headers)).json()
    assert listed["state"] == "warm" and worker.pool.sessions() == [uuid.UUID(session_id)]
    assert any(k.endswith(f"/sessions/{session_id}/transcript") for k in storage.objects)

    # Turn 2: the same sandbox (no new one), resuming the same conversation.
    claude.edits = {"src/refunds.py": "def refund(amount):\n    assert amount > 0\n    return amount\n"}
    turns = f"{base}/coding/sessions/{session_id}/turns"
    second = (await db_client.post(turns, json={"message": "Only positive amounts"}, headers=ada.headers)).json()
    second = await _approve(db_client, base, second, ada.headers)
    assert second["status"] == "pr_opened" and sandbox.opened == 1
    assert claude.argvs[1][claude.argvs[1].index("--resume") + 1] == conversation
    assert claude.found_transcript[1] == "turn 1\n"  # the warm sandbox still had it
    assert any("kept from the last turn" in e["text"] and "continuing the session" in e["text"] for e in second["events"])
    assert second["files_changed"] == [{"path": "src/refunds.py", "added": 1, "removed": 0}]  # only this turn's change

    # A restart: no warm sandbox. Turn 3 gets a fresh one with the transcript restored, and resumes.
    await worker.pool.close_all()
    claude.edits = {"src/refunds.py": "def refund(amount):\n    assert amount > 0, 'positive'\n    return amount\n"}
    third = (await db_client.post(turns, json={"message": "Say why"}, headers=ada.headers)).json()
    third = await _approve(db_client, base, third, ada.headers)
    assert third["status"] == "pr_opened" and sandbox.opened == 2
    assert claude.found_transcript[2] == "turn 1\nturn 2\n"  # restored from storage
    assert claude.argvs[2][claude.argvs[2].index("--resume") + 1] == conversation

    # Closing it by hand: its sandbox goes; its transcript, branch, and PR stay.
    assert (await db_client.post(f"{base}/coding/sessions/{session_id}/close", headers=ada.headers)).status_code == 204
    await worker.reap()
    assert worker.pool.sessions() == [] and any(k.endswith(f"/sessions/{session_id}/transcript") for k in storage.objects)
    [listed] = (await db_client.get(f"{ws}/coding/sessions", headers=ada.headers)).json()
    assert listed["state"] == "closed" and listed["pr_number"] == first["pr_number"]

    # A new turn opens it again and resumes from the transcript.
    agent_script.say("Once more.")
    claude.edits = {"src/refunds.py": "def refund(amount):\n    assert amount > 0, 'must be positive'\n    return amount\n"}
    fourth = (await db_client.post(turns, json={"message": "Clearer message"}, headers=ada.headers)).json()
    fourth = await _approve(db_client, base, fourth, ada.headers)
    assert fourth["status"] == "pr_opened" and claude.found_transcript[3] == "turn 1\nturn 2\nturn 3\n"
    [listed] = (await db_client.get(f"{ws}/coding/sessions", headers=ada.headers)).json()
    assert listed["state"] == "warm"

    # Renamed, pinned, archived (hidden from the list unless asked for).
    patch = f"{base}/coding/sessions/{session_id}"
    assert (await db_client.patch(patch, json={"title": "Refund rules", "pinned": True}, headers=ada.headers)).status_code == 204
    [listed] = (await db_client.get(f"{ws}/coding/sessions", headers=ada.headers)).json()
    assert listed["title"] == "Refund rules" and listed["pinned"] and listed["issue_title"] == "Refunds"
    assert (await db_client.patch(patch, json={"archived": True}, headers=ada.headers)).status_code == 204
    assert (await db_client.get(f"{ws}/coding/sessions", headers=ada.headers)).json() == []
    [listed] = (await db_client.get(f"{ws}/coding/sessions", params={"archived": "only"}, headers=ada.headers)).json()
    assert listed["archived"]

    # Deleting it: its turns and transcript go (and its sandbox); the PR stays on GitHub.
    assert (await db_client.delete(patch, headers=ada.headers)).status_code == 204
    await worker.reap()
    assert not any(k.endswith("/transcript") for k in storage.objects) and worker.pool.sessions() == []
    assert (await db_client.get(f"{ws}/coding/sessions", params={"archived": "include"}, headers=ada.headers)).json() == []
    assert (await db_client.get(f"{base}/coding/runs/{first['id']}", headers=ada.headers)).status_code == 404
    assert len(github.pulls) == 1
