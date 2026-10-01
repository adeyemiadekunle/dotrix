"""Pipelines on the platform (docs/agents-v2.md §4.7, §5): checkpoints a person answers, tokens per
stage, findings deduplicated, and the triage and issue-review entry points."""
import pytest
from httpx import AsyncClient
from langchain_core.messages import AIMessage

from pmagent_backend.modules.workspaces.models import Role
from pmagent_engine.testing import tool_call


@pytest.fixture
def world(db_client: AsyncClient, create_team, signup, add_member):
    """Ada owns a team with project KUN; Bob is an admin, Cat and Dan are members."""

    async def _make():
        ada = await signup()
        bob = await signup(email="bob@example.com", name="Bob")
        cat = await signup(email="cat@example.com", name="Cat")
        dan = await signup(email="dan@example.com", name="Dan")
        team = await create_team(ada.headers)
        await add_member(team["id"], bob.id, Role.ADMIN)
        await add_member(team["id"], cat.id, Role.MEMBER)
        await add_member(team["id"], dan.id, Role.MEMBER)
        project = (await db_client.post(f"/v1/workspaces/{team['id']}/projects", json={"key": "KUN", "name": "Kunemi"},
                                        headers=ada.headers)).json()
        ws = f"/v1/workspaces/{team['id']}"
        return ada, bob, cat, dan, ws, f"{ws}/projects/{project['id']}"

    return _make


def _checkpoint() -> AIMessage:
    return tool_call("checkpoint", summary="Three specialists, eight steps", plan=["Spec it", "Assess impact"])


async def _paused(db_client: AsyncClient, base: str, headers) -> dict:
    run = (await db_client.post(f"{base}/agent/runs", json={"message": "Plan the multi-zone launch"},
                                headers=headers)).json()
    assert run["status"] == "awaiting_approval", run
    [approval] = run["approvals"]
    assert approval["tool"] == "checkpoint" and approval["args"]["plan"] == ["Spec it", "Assess impact"]
    return run


def _decide(approval: dict, decision: str, reason: str | None = None) -> dict:
    return {"decisions": [{"approval_id": approval["id"], "decision": decision, "reason": reason}]}


async def test_a_member_continues_their_own_runs_checkpoint(world, db_client: AsyncClient, agent_script) -> None:
    _, _, cat, dan, _, base = await world()
    agent_script.say(_checkpoint(), "Here's the plan, done.")
    run = await _paused(db_client, base, cat.headers)
    url = f"{base}/agent/runs/{run['id']}/decisions"
    # Another member can't answer it; Cat, who asked, can (members can't approve changes).
    assert (await db_client.post(url, json=_decide(run["approvals"][0], "approve"), headers=dan.headers)).status_code == 403
    done = await db_client.post(url, json=_decide(run["approvals"][0], "approve"), headers=cat.headers)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed" and done.json()["reply"] == "Here's the plan, done."
    assert done.json()["approvals"][0]["status"] == "approved"


async def test_steering_sends_the_changes_back_and_is_audited(world, db_client: AsyncClient, agent_script) -> None:
    ada, bob, _, _, ws, base = await world()
    model = agent_script.say(_checkpoint(), "Adjusted: just the spec.")
    run = await _paused(db_client, base, ada.headers)
    url = f"{base}/agent/runs/{run['id']}/decisions"
    # Steer needs the changes.
    assert (await db_client.post(url, json=_decide(run["approvals"][0], "steer"), headers=bob.headers)).status_code == 422
    done = await db_client.post(url, json=_decide(run["approvals"][0], "steer", "Skip the impact"), headers=bob.headers)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed"
    heard = str(model.received[-1][-1].content)
    assert "The person wants changes to your plan: Skip the impact" in heard
    audit = (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()
    steered = next(e for e in audit if e["action"] == "checkpoint.steered")
    assert steered["approved_by_id"] is None and steered["details"]["reason"] == "Skip the impact"


async def test_stopping_at_a_checkpoint_tells_the_agent_to_wrap_up(world, db_client: AsyncClient, agent_script) -> None:
    ada, _, _, _, _, base = await world()
    model = agent_script.say(_checkpoint(), "Stopped; here's what I found.")
    run = await _paused(db_client, base, ada.headers)
    done = (await db_client.post(f"{base}/agent/runs/{run['id']}/decisions",
                                 json=_decide(run["approvals"][0], "reject", "Not now"), headers=ada.headers)).json()
    assert done["status"] == "completed" and done["approvals"][0]["status"] == "rejected"
    assert "The person stopped here: Not now" in str(model.received[-1][-1].content)


async def test_steer_only_answers_checkpoints_and_members_still_cant_approve(
    world, db_client: AsyncClient, agent_script
) -> None:
    ada, _, cat, _, _, base = await world()
    agent_script.say(tool_call("write_file", file_path="/pmagent/roadmap.md", content="# R\n"), "Done.")
    run = (await db_client.post(f"{base}/agent/runs", json={"message": "Update the roadmap"}, headers=cat.headers)).json()
    assert run["status"] == "awaiting_approval"
    url = f"{base}/agent/runs/{run['id']}/decisions"
    [approval] = run["approvals"]
    assert (await db_client.post(url, json=_decide(approval, "approve"), headers=cat.headers)).status_code == 403
    assert (await db_client.post(url, json=_decide(approval, "steer", "x"), headers=ada.headers)).status_code == 422


async def test_tokens_are_split_by_stage(world, db_client: AsyncClient, agent_script) -> None:
    ada, _, _, _, _, base = await world()
    usage = {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}
    stage = tool_call("stage", current="classify")
    stage.usage_metadata = usage
    reply = AIMessage(content="It's a question.", usage_metadata={"input_tokens": 200, "output_tokens": 20, "total_tokens": 220})
    agent_script.say(stage, reply)
    run = (await db_client.post(f"{base}/agent/runs", json={"message": "What is this?"}, headers=ada.headers)).json()
    assert run["status"] == "completed"
    # The call that names the stage belongs to what came before; the next call is in it.
    assert run["breakdown"]["by_stage"] == [
        {"agent": "project-manager", "stage": "classify", "input_tokens": 200, "output_tokens": 20, "model_calls": 1}
    ]


async def test_repeated_findings_are_settled_not_shown_twice(world, db_client: AsyncClient, agent_script) -> None:
    ada, _, _, _, _, base = await world()
    issue = await db_client.post(f"{base}/issues", json={"type": "task", "title": "Rotate keys"}, headers=ada.headers)
    assert issue.status_code == 201

    def review():
        return tool_call("submit_result", items=[
            {"severity": "high", "title": "Token in logs", "detail": "auth.py logs it", "refs": ["auth.py"]},
            {"severity": "medium", "title": "Rotate keys!", "detail": "Keys never rotate"},
        ])

    agent_script.say(review(), "Two findings.", review(), "Same again.")
    first = (await db_client.post(f"{base}/agent/runs", json={"message": "review", "agent": "reviewer"},
                                  headers=ada.headers)).json()
    items = first["outputs"][0]["items"]
    assert [i["state"] for i in items] == ["open", "done"]
    assert items[1]["link"] == "KUN-1" and items[1]["reason"] == "Already on the board as KUN-1"
    assert items[0]["data"]["fingerprint"]
    second = (await db_client.post(f"{base}/agent/runs", json={"message": "review again", "agent": "reviewer"},
                                   headers=ada.headers)).json()
    items = second["outputs"][0]["items"]
    assert items[0]["state"] == "dismissed" and items[0]["reason"] == "Same as an open finding from an earlier run"


async def test_triage_a_report(world, db_client: AsyncClient, agent_script) -> None:
    _, _, cat, _, _, base = await world()
    model = agent_script.say(
        tool_call("stage", current="duplicates"),
        tool_call("create_issue", type="bug", title="Wrong zone shown", description="Drivers see the wrong zone"),
    )
    run = (await db_client.post(f"{base}/agent/triage", json={"report": "Drivers see the wrong zone\nSince Monday"},
                                headers=cat.headers)).json()
    assert run["mode"] == "pm.triage" and run["agent"] == "auto" and run["title"] == "Triage: Drivers see the wrong zone"
    assert run["status"] == "awaiting_approval" and run["approvals"][0]["tool"] == "create_issue"
    system = str(model.received[0][0].content)
    assert "## How you work: Triage a report" in system
    assert "Drivers see the wrong zone" in str(model.received[0][-1].content)


async def test_review_an_issue(world, db_client: AsyncClient, agent_script) -> None:
    ada, _, _, _, _, base = await world()
    await db_client.post(f"{base}/issues", json={"type": "task", "title": "Retry uploads"}, headers=ada.headers)
    assert (await db_client.post(f"{base}/agent/issues/KUN-9/review", headers=ada.headers)).status_code == 404
    model = agent_script.say(
        tool_call("submit_result", items=[{"severity": "medium", "title": "No retry test", "detail": "Criterion 2"}]),
        "Send it back.",
    )
    run = (await db_client.post(f"{base}/agent/issues/KUN-1/review", headers=ada.headers)).json()
    assert run["mode"] == "reviewer.issue" and run["agent"] == "reviewer" and run["title"] == "Review KUN-1"
    assert run["status"] == "completed" and run["reply"] == "Send it back."
    assert run["outputs"][0]["kind"] == "finding"
    assert "## How you work: Review an issue" in str(model.received[0][0].content)
    assert "Review KUN-1 (Retry uploads" in str(model.received[0][-1].content)
