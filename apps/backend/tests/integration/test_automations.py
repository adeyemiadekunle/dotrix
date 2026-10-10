"""Automations: agents that run on a schedule or when people change things (agents v2 step 4)."""
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import update

from dotrix_backend.modules.automations.models import Automation
from dotrix_backend.modules.automations.service import next_run
from dotrix_backend.modules.workspaces.models import Role
from dotrix_engine.testing import tool_call


async def _world(db_client: AsyncClient, signup, create_team, add_member):
    ada = await signup()
    cat = await signup(email="cat@example.com", name="Cat")
    team = await create_team(ada.headers)
    await add_member(team["id"], cat.id, Role.MEMBER)
    ws = f"/v1/workspaces/{team['id']}"
    project = (await db_client.post(f"{ws}/projects", json={"key": "KUN", "name": "K"}, headers=ada.headers)).json()
    return ada, cat, team, f"{ws}/projects/{project['id']}"


async def _tick(db_client: AsyncClient) -> None:
    """The minute's run_automations (the worker's cron, or the API's loop)."""
    await db_client._transport.app.state.jobs.enqueue("run_automations")  # type: ignore[attr-defined]


async def _runs(db_client: AsyncClient, base: str, headers) -> list[dict]:
    return (await db_client.get(f"{base}/agent/runs", headers=headers)).json()


def test_next_run() -> None:
    monday_9 = datetime(2026, 10, 5, 9, 30, tzinfo=UTC)  # a Monday
    assert next_run(None, None, monday_9) is None
    assert next_run(10, None, monday_9) == datetime(2026, 10, 5, 10, tzinfo=UTC)
    assert next_run(8, None, monday_9) == datetime(2026, 10, 6, 8, tzinfo=UTC)
    assert next_run(9, 0, monday_9) == datetime(2026, 10, 12, 9, tzinfo=UTC)  # 9:00 Monday has passed
    assert next_run(9, 4, monday_9) == datetime(2026, 10, 9, 9, tzinfo=UTC)  # Friday


async def test_set_up_and_who_may(db_client: AsyncClient, signup, create_team, add_member) -> None:
    ada, cat, _, base = await _world(db_client, signup, create_team, add_member)
    body = {"name": "Weekly status", "agent": "documentation", "instructions": "Update current-state.md.",
            "schedule_hour": 8, "schedule_weekday": 0}
    assert (await db_client.post(f"{base}/automations", json=body, headers=cat.headers)).status_code == 403
    res = await db_client.post(f"{base}/automations", json=body, headers=ada.headers)
    assert res.status_code == 201, res.text
    made = res.json()
    assert made["agent"] == "documentation" and made["created_by_id"] == ada.id and made["next_run_at"]
    # Members see what runs in their project.
    assert [a["name"] for a in (await db_client.get(f"{base}/automations", headers=cat.headers)).json()] == ["Weekly status"]

    bad = [
        {**body, "agent": "nobody"},
        {"name": "x", "instructions": "y"},  # neither events nor a schedule
        {**body, "schedule_hour": None},  # a weekday without an hour
        {**body, "events": ["issue.exploded"]},
    ]
    for payload in bad:
        assert (await db_client.post(f"{base}/automations", json=payload, headers=ada.headers)).status_code == 422

    url = f"{base}/automations/{made['id']}"
    off = (await db_client.patch(url, json={"enabled": False}, headers=ada.headers)).json()
    assert off["enabled"] is False and off["next_run_at"] is None
    assert (await db_client.patch(url, json={"schedule_hour": None}, headers=ada.headers)).status_code == 422
    assert (await db_client.delete(url, headers=cat.headers)).status_code == 403
    assert (await db_client.delete(url, headers=ada.headers)).status_code == 204
    actions = {e["action"] for e in (await db_client.get(f"{base.split('/projects')[0]}/audit", headers=ada.headers)).json()}
    assert {"automation.created", "automation.updated", "automation.deleted"} <= actions


async def test_people_s_changes_set_it_off_and_agents_don_t(
    db_client: AsyncClient, signup, create_team, add_member, agent_script
) -> None:
    ada, cat, _, base = await _world(db_client, signup, create_team, add_member)
    made = (await db_client.post(f"{base}/automations", json={
        "name": "Triage new issues", "instructions": "Triage the new issues.", "events": ["issue.created"],
    }, headers=ada.headers)).json()

    for title in ("Login fails on Safari", "Export is slow"):
        await db_client.post(f"{base}/issues", json={"type": "task", "title": title}, headers=cat.headers)
    model = agent_script.say("Both triaged.")
    await _tick(db_client)
    runs = await _runs(db_client, base, ada.headers)
    assert len(runs) == 1  # both events, one run
    run = runs[0]
    assert run["automation_id"] == made["id"] and run["title"] == "Automation: Triage new issues"
    message = model.received[0][-1].content
    assert message.startswith("Triage the new issues.") and "because an issue was created" in message
    assert "KUN-1 created: Login fails on Safari" in message and "KUN-2 created: Export is slow" in message
    # Instructed by whoever set it up, in the automation's own conversation.
    read = (await db_client.get(f"{base}/automations", headers=ada.headers)).json()[0]
    assert read["last_run_id"] == run["id"] and read["thread_id"] == run["thread_id"] and read["runs_today"] == 1
    await _tick(db_client)
    assert len(await _runs(db_client, base, ada.headers)) == 1  # nothing new happened

    # An agent creating an issue (an approved change) doesn't set it off.
    agent_script.say(tool_call("create_issue", type="task", title="Add retries"), "Created it.")
    chat = (await db_client.post(f"{base}/agent/runs", json={"message": "create an issue"}, headers=ada.headers)).json()
    pending = [a for a in chat["approvals"] if a["status"] == "pending"]
    await db_client.post(f"{base}/agent/runs/{chat['id']}/decisions", headers=ada.headers,
                         json={"decisions": [{"approval_id": a["id"], "decision": "approve"} for a in pending]})
    await _tick(db_client)
    assert [r["automation_id"] for r in await _runs(db_client, base, ada.headers)].count(made["id"]) == 1


async def test_approved_changes_keep_documents_current_without_looping(
    db_client: AsyncClient, signup, create_team, add_member, agent_script
) -> None:
    ada, _, _, base = await _world(db_client, signup, create_team, add_member)
    made = (await db_client.post(f"{base}/automations", json={
        "name": "Keep documents current", "agent": "documentation", "events": ["changes.approved"],
        "instructions": "Bring current-state.md up to date with what changed.",
    }, headers=ada.headers)).json()

    async def approve_all(run: dict) -> dict:
        pending = [a for a in run["approvals"] if a["status"] == "pending"]
        res = await db_client.post(f"{base}/agent/runs/{run['id']}/decisions", headers=ada.headers,
                                   json={"decisions": [{"approval_id": a["id"], "decision": "approve"} for a in pending]})
        return res.json()

    model = agent_script.say(
        tool_call("write_file", file_path="/dotrix/roadmap.md", content="# Roadmap\n\nQ4: payments\n"), "Done.",
        # the automation's run, which changes a document too
        tool_call("edit_file", file_path="/dotrix/current-state.md", old_string="", new_string="Payments in Q4.\n"),
        "Updated.",
    )
    chat = (await db_client.post(f"{base}/agent/runs", json={"message": "plan payments for Q4"}, headers=ada.headers)).json()
    assert (await approve_all(chat))["status"] == "completed"
    await _tick(db_client)
    runs = [r for r in await _runs(db_client, base, ada.headers) if r["automation_id"] == made["id"]]
    assert len(runs) == 1 and runs[0]["status"] == "awaiting_approval"
    assert "roadmap.md" in model.received[2][-1].content  # what changed, as data
    # Approving the automation's own changes doesn't set it off again.
    await approve_all(runs[0])
    await _tick(db_client)
    assert len([r for r in await _runs(db_client, base, ada.headers) if r["automation_id"] == made["id"]]) == 1


async def test_schedule_limits_and_lost_access(
    db_client: AsyncClient, signup, create_team, add_member, agent_script, db_session
) -> None:
    ada, cat, team, base = await _world(db_client, signup, create_team, add_member)
    await db_client.patch(f"/v1/workspaces/{team['id']}/members/{cat.id}", json={"role": "admin"}, headers=ada.headers)
    made = (await db_client.post(f"{base}/automations", json={
        "name": "Daily summary", "instructions": "Summarise the day.", "schedule_hour": 18, "max_runs_per_day": 2,
    }, headers=cat.headers)).json()

    # Its time comes round: it runs, and the next time moves on a day.
    await db_session.execute(update(Automation).values(next_run_at=datetime.now(UTC) - timedelta(minutes=1)))
    await db_session.commit()
    agent_script.say("Summary one.", "Summary two.", "Summary three.")
    await _tick(db_client)
    read = (await db_client.get(f"{base}/automations", headers=ada.headers)).json()[0]
    assert read["runs_today"] == 1 and "on its schedule, every day at 18:00 UTC" in agent_script.model.received[0][-1].content
    assert datetime.fromisoformat(read["next_run_at"]) > datetime.now(UTC)

    # Run now, up to its daily limit; then it says why not.
    url = f"{base}/automations/{made['id']}/run"
    assert (await db_client.post(url, headers=ada.headers)).json()["runs_today"] == 2
    limited = (await db_client.post(url, headers=ada.headers)).json()
    assert limited["runs_today"] == 2 and "limit of 2 runs today" in limited["last_error"]

    # Whoever set it up leaves: it turns itself off rather than run on their authority.
    await db_client.delete(f"/v1/workspaces/{team['id']}/members/{cat.id}", headers=ada.headers)
    await db_client.patch(f"{base}/automations/{made['id']}", json={"max_runs_per_day": 5}, headers=ada.headers)
    gone = (await db_client.post(url, headers=ada.headers)).json()
    assert gone["enabled"] is False and "can no longer ask agents" in gone["last_error"]


async def test_a_run_waiting_for_a_decision_isn_t_doubled(
    db_client: AsyncClient, signup, create_team, add_member, agent_script
) -> None:
    ada, _, _, base = await _world(db_client, signup, create_team, add_member)
    made = (await db_client.post(f"{base}/automations", json={
        "name": "Roadmap", "instructions": "Update the roadmap.", "schedule_hour": 6,
    }, headers=ada.headers)).json()
    agent_script.say(tool_call("write_file", file_path="/dotrix/roadmap.md", content="# R\n"), "Done.")
    url = f"{base}/automations/{made['id']}/run"
    assert (await db_client.post(url, headers=ada.headers)).json()["last_error"] is None
    again = (await db_client.post(url, headers=ada.headers)).json()
    assert "still going or waiting for a decision" in again["last_error"] and again["runs_today"] == 1
