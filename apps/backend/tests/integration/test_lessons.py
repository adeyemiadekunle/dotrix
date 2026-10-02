"""Lessons (agents v2 step 2): rejections and dismissals with reasons become lessons owners
accept into an agent's rules; folder templates every agent follows."""
from httpx import AsyncClient

from pmagent_backend.modules.workspaces.models import Role
from pmagent_engine.testing import tool_call


async def _world(db_client: AsyncClient, signup, create_team, add_member):
    ada = await signup()
    cat = await signup(email="cat@example.com", name="Cat")
    team = await create_team(ada.headers)
    await add_member(team["id"], cat.id, Role.MEMBER)
    ws = f"/v1/workspaces/{team['id']}"
    project = (await db_client.post(f"{ws}/projects", json={"key": "KUN", "name": "K"}, headers=ada.headers)).json()
    return ada, cat, ws, f"{ws}/projects/{project['id']}"


async def _decide(db_client: AsyncClient, base: str, run: dict, headers, decision: str, reason: str | None = None):
    pending = [a for a in run["approvals"] if a["status"] == "pending"]
    return (await db_client.post(f"{base}/agent/runs/{run['id']}/decisions", headers=headers, json={"decisions": [
        {"approval_id": a["id"], "decision": decision, "reason": reason} for a in pending
    ]})).json()


async def test_a_rejection_teaches_the_agent_once_accepted(
    db_client: AsyncClient, signup, create_team, add_member, agent_script
) -> None:
    ada, cat, ws, base = await _world(db_client, signup, create_team, add_member)
    model = agent_script.say(
        tool_call("write_file", file_path="/pmagent/roadmap.md", content="# Roadmap\n\nEverything in Q1\n"), "Ok.",
        tool_call("write_file", file_path="/pmagent/vision.md", content="# Vision\n"), "Ok.",
        "Planned it in quarters.",
    )
    run = (await db_client.post(f"{base}/agent/runs", json={"message": "plan the year"}, headers=ada.headers)).json()
    await _decide(db_client, base, run, ada.headers, "reject", "Plan by quarter, never everything at once")
    # Without a reason there's nothing to learn.
    run = (await db_client.post(f"{base}/agent/runs", json={"message": "vision"}, headers=ada.headers)).json()
    await _decide(db_client, base, run, ada.headers, "reject")

    # Owners and admins decide; members don't see them.
    assert (await db_client.get(f"{base}/lessons", headers=cat.headers)).status_code == 403
    lessons = (await db_client.get(f"{base}/lessons?status=proposed", headers=ada.headers)).json()
    assert len(lessons) == 1
    lesson = lessons[0]
    assert lesson["agent"] == "project-manager" and lesson["source"] == "rejection"
    assert "roadmap.md" in lesson["text"] and "Plan by quarter" in lesson["text"]

    url = f"{base}/lessons/{lesson['id']}"
    accepted = await db_client.post(f"{url}/accept", json={"text": "Plan roadmaps by quarter."}, headers=ada.headers)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    assert (await db_client.post(f"{url}/decline", headers=ada.headers)).status_code == 409
    file = (await db_client.get(f"{base}/knowledge/files/agent-rules/lessons/project-manager.md", headers=ada.headers)).json()
    assert file["content"].startswith("# Lessons for the project-manager agent") and "- Plan roadmaps by quarter." in file["content"]
    actions = {e["action"] for e in (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()}
    assert "lesson.accepted" in actions

    # The next run's agent reads it, and the folder templates.
    await db_client.post(f"{base}/agent/runs", json={"message": "and next year?"}, headers=ada.headers)
    system = model.received[-1][0].content
    assert "## Lessons from this project\n" in system and "- Plan roadmaps by quarter." in system
    assert "agent-rules/templates/<folder>.md" in system


async def test_a_dismissed_finding_proposes_a_lesson_for_its_agent(
    db_client: AsyncClient, signup, create_team, add_member, agent_script
) -> None:
    ada, _, _, base = await _world(db_client, signup, create_team, add_member)
    agent_script.say(
        tool_call("submit_result", items=[{"title": "No tests for login", "severity": "low", "detail": "x"}]),
        "One finding.",
    )
    run = (await db_client.post(f"{base}/agent/runs", json={"message": "review", "agent": "reviewer"},
                                headers=ada.headers)).json()
    assert run["outputs"], run
    output = run["outputs"][0]
    url = f"{base}/agent/runs/{run['id']}/outputs/{output['id']}/items/0"
    res = await db_client.patch(url, json={"state": "dismissed", "reason": "Login is covered by e2e"}, headers=ada.headers)
    assert res.status_code == 200, res.text
    await db_client.patch(url, json={"state": "dismissed", "reason": "Again"}, headers=ada.headers)  # no second one
    lessons = (await db_client.get(f"{base}/lessons", headers=ada.headers)).json()
    assert len(lessons) == 1
    assert lessons[0]["agent"] == "reviewer" and lessons[0]["source"] == "dismissal"
    assert '"No tests for login"' in lessons[0]["text"]
    declined = (await db_client.post(f"{base}/lessons/{lessons[0]['id']}/decline", headers=ada.headers)).json()
    assert declined["status"] == "declined"


async def test_new_projects_have_folder_templates(db_client: AsyncClient, signup, create_team, add_member) -> None:
    ada, _, _, base = await _world(db_client, signup, create_team, add_member)
    for folder in ("requirements", "decisions", "research", "design"):
        res = await db_client.get(f"{base}/knowledge/files/agent-rules/templates/{folder}.md", headers=ada.headers)
        assert res.status_code == 200, (folder, res.text)
