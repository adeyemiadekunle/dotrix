"""Juno on GitHub: its review of Kai's PR posted there, and a failed CI on Kai's PR looked at."""
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import select

from apps.backend.tests.integration.conftest import _deliver
from apps.backend.tests.integration.test_coding import (  # noqa: F401  (fixtures)
    ScriptedClaude,
    _approve,
    claude,
    coding,
    origin,
)
from dotrix_backend.modules.audit.models import AuditEvent
from dotrix_backend.modules.coding.github_reviews import diff_lines, review_comments
from dotrix_engine.testing import tool_call

DIFF = """diff --git a/src/payments.py b/src/payments.py
index 1111111..2222222 100644
--- a/src/payments.py
+++ b/src/payments.py
@@ -1,2 +1,4 @@
 class PaymentProvider:
-    pass
+    def refund(self, amount):
+        return amount
"""


def test_findings_go_on_the_diff_lines_they_cite() -> None:
    assert diff_lines(DIFF) == {"src/payments.py": {1, 2, 3}}
    inline, rest = review_comments([
        {"severity": "high", "title": "No check", "detail": "Negative amounts refund.", "refs": ["src/payments.py:3"]},
        {"severity": "low", "title": "Elsewhere", "detail": "Not in the diff.", "refs": ["src/payments.py:40"]},
        {"severity": "medium", "title": "No test", "detail": "Add one."},
    ], DIFF)
    assert [(c["path"], c["line"]) for c in inline] == [("src/payments.py", 3)]
    assert "**High: No check**" in inline[0]["body"]
    assert [f["title"] for f in rest] == ["Elsewhere", "No test"]


async def _turn(db_client: AsyncClient, coding, claude: ScriptedClaude, agent_script, *replies) -> dict:  # noqa: F811
    ada, _, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", headers=ada.headers, json={
        "type": "task", "title": "Refund a payment", "description": "refund() returns the amount."})).json()
    claude.edits = {"src/payments.py": "class PaymentProvider:\n    def refund(self, amount):\n        return amount\n"}
    agent_script.say(*replies)
    asked = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", headers=ada.headers, json={})).json()
    run = await _approve(db_client, base, asked, ada.headers)
    assert run["status"] == "pr_opened", run
    return (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()


async def _audit(db_session, action: str) -> list[AuditEvent]:
    return list(await db_session.scalars(select(AuditEvent).where(AuditEvent.action == action)))


async def test_juno_review_is_posted_on_the_pr_as_a_comment(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude, agent_script, db_session,  # noqa: F811
) -> None:
    run = await _turn(db_client, coding, claude, agent_script,
                      tool_call("submit_result", items=[
                          {"severity": "high", "title": "Negative refunds", "detail": "refund(-5) pays out.",
                           "refs": ["src/payments.py:3"]},
                          {"severity": "medium", "title": "No test", "detail": "Add one for refund()."},
                      ]),
                      "Two things to fix before merging.")
    [review] = github.reviews
    assert (review["repo"], review["number"], review["event"]) == ("kunemi/api", run["pr_number"], "COMMENT")
    assert review["commit_id"] == run["commit_sha"]
    assert [(c["path"], c["line"], c["side"]) for c in review["comments"]] == [("src/payments.py", 3, "RIGHT")]
    assert "Negative refunds" in review["comments"][0]["body"]
    assert "Two things to fix" in review["body"] and "No test" in review["body"] and "not an approval" in review["body"]
    assert run["review_posted_url"].startswith("https://github.com/kunemi/api/pull/1#pullrequestreview-")
    [entry] = await _audit(db_session, "coding.review_posted")
    assert entry.agent == "reviewer" and entry.details["pr"] == run["pr_number"]


async def test_a_review_github_refuses_inline_goes_in_the_body(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude, agent_script,  # noqa: F811
) -> None:
    github.reject_inline = True
    await _turn(db_client, coding, claude, agent_script,
                tool_call("submit_result", items=[{"severity": "high", "title": "Negative refunds",
                                                   "detail": "refund(-5) pays out.", "refs": ["src/payments.py:3"]}]),
                "One thing.")
    [review] = github.reviews
    assert "comments" not in review and "`src/payments.py:3`" in review["body"] and "Negative refunds" in review["body"]


async def test_reviews_on_github_can_be_switched_off(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude, agent_script,  # noqa: F811
) -> None:
    db_client._transport.app.state.settings.github_pr_reviews = False  # type: ignore[attr-defined]
    run = await _turn(db_client, coding, claude, agent_script, "Looks right.")
    assert github.reviews == [] and run["review_posted_url"] is None and run["review_run_id"]


def _suite(sha: str, conclusion: str) -> dict:
    return {"action": "completed", "repository": {"id": 9001, "full_name": "kunemi/api"},
            "check_suite": {"head_sha": sha, "conclusion": conclusion, "status": "completed"}}


async def test_a_failed_ci_on_kais_pr_gets_junos_look(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude, agent_script, db_session,  # noqa: F811
) -> None:
    ada, _, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    run = await _turn(db_client, coding, claude, agent_script, "Looks right.")
    assert run["ci_state"] is None
    sha = run["commit_sha"]
    github.ci_runs = [{"id": 7, "name": "CI", "head_sha": sha, "conclusion": "failure", "html_url": "https://ci/7",
                       "jobs": [{"id": 70, "name": "pytest", "conclusion": "failure", "html_url": "https://ci/7/70",
                                 "log": "collected 3 items\nFAILED tests/test_refund.py::test_negative - assert -5 >= 0\n"},
                                {"id": 71, "name": "lint", "conclusion": "success", "log": "ok"}]}]
    agent_script.say(tool_call("submit_result", items=[
        {"severity": "high", "title": "refund() accepts negatives", "detail": "test_negative fails.",
         "suggested_fix": "Raise ValueError for amount < 0."}]), "The change lets negative refunds through.")
    sent = await _deliver(db_client, "check_suite", _suite(sha, "failure"))
    assert sent.status_code in (200, 202), sent.text
    read = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert read["ci_state"] == "failed" and read["ci_review_run_id"], read
    look = (await db_client.get(f"{base}/agent/runs/{read['ci_review_run_id']}", headers=ada.headers)).json()
    assert "scope-a-failing-build" in look["message"] and "FAILED tests/test_refund.py::test_negative" in look["message"]
    assert '<data source="CI job CI / pytest' in look["message"] and "lint" not in look["message"].split("<data")[1][:40]
    [comment] = github.comments
    assert comment["number"] == run["pr_number"] and "negative refunds" in comment["body"]
    assert "Raise ValueError" in comment["body"]
    assert [t for t in github.token_requests if t.get("permissions", {}).get("actions") == "read"]
    assert await _audit(db_session, "coding.ci_review_posted")
    # The same failure delivered again (a re-run of the suite) doesn't start a second look.
    await _deliver(db_client, "check_suite", _suite(sha, "failure"))
    again = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert again["ci_review_run_id"] == read["ci_review_run_id"] and len(github.comments) == 1
    # Another suite passing on the same commit keeps it failed.
    await _deliver(db_client, "check_suite", _suite(sha, "success"))
    assert (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()["ci_state"] == "failed"


async def test_a_passing_ci_is_recorded_and_other_commits_are_ignored(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude, agent_script,  # noqa: F811
) -> None:
    ada, _, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    run = await _turn(db_client, coding, claude, agent_script, "Looks right.")
    await _deliver(db_client, "check_suite", _suite("0" * 40, "failure"))  # not Kai's commit
    assert (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()["ci_state"] is None
    await _deliver(db_client, "check_suite", _suite(run["commit_sha"], "success"))
    read = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    assert read["ci_state"] == "passed" and read["ci_review_run_id"] is None and github.comments == []


async def test_without_actions_permission_juno_is_told_the_logs_couldnt_be_read(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude, agent_script,  # noqa: F811
) -> None:
    ada, _, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    run = await _turn(db_client, coding, claude, agent_script, "Looks right.")
    github.refuse_actions = True
    agent_script.say("I couldn't read the logs; open the PR's Checks.")
    await _deliver(db_client, "check_suite", _suite(run["commit_sha"], "failure"))
    read = (await db_client.get(f"{base}/coding/runs/{run['id']}", headers=ada.headers)).json()
    look = (await db_client.get(f"{base}/agent/runs/{read['ci_review_run_id']}", headers=ada.headers)).json()
    assert "needs the Actions (read) permission" in look["message"]
