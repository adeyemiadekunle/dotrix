"""Rules that layer (agents v2 step 2): workspace rules under each project's, and skills."""
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import update

from pmagent_backend.modules.agents.models import AgentRun
from pmagent_backend.modules.workspaces.models import Role


async def _world(db_client: AsyncClient, signup, create_team, add_member):
    ada = await signup()
    cat = await signup(email="cat@example.com", name="Cat")
    team = await create_team(ada.headers)
    await add_member(team["id"], cat.id, Role.MEMBER)
    ws = f"/v1/workspaces/{team['id']}"
    project = (await db_client.post(f"{ws}/projects", json={"key": "KUN", "name": "K"}, headers=ada.headers)).json()
    return ada, cat, ws, f"{ws}/projects/{project['id']}"


async def test_workspace_rules_come_before_the_project_s(
    db_client: AsyncClient, signup, create_team, add_member, agent_script
) -> None:
    ada, cat, ws, base = await _world(db_client, signup, create_team, add_member)
    body = {"content": "Write in British English.", "base_version": 0}
    assert (await db_client.put(f"{ws}/rules/base", json=body, headers=cat.headers)).status_code == 403
    saved = await db_client.put(f"{ws}/rules/base", json=body, headers=ada.headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 1
    assert (await db_client.put(f"{ws}/rules/base", json=body, headers=ada.headers)).status_code == 409  # stale
    research = {"content": "Prefer primary sources.", "base_version": 0}
    assert (await db_client.put(f"{ws}/rules/research", json=research, headers=ada.headers)).status_code == 200
    assert (await db_client.put(f"{ws}/rules/nobody", json=research, headers=ada.headers)).status_code == 404
    listed = (await db_client.get(f"{ws}/rules", headers=cat.headers)).json()
    assert [r["handle"] for r in listed] == ["base", "research"]

    await db_client.put(f"{base}/knowledge/files/agent-rules/base.md", headers=ada.headers,
                        json={"content": "# Project rules\nThis project writes in US English."})
    model = agent_script.say("Hello.")
    await db_client.post(f"{base}/agent/runs", json={"message": "hi"}, headers=ada.headers)
    system = model.received[0][0].content
    workspace_at = system.index("Write in British English.")
    project_at = system.index("This project writes in US English.")
    assert workspace_at < project_at  # the project's, more specific, come last
    assert "## Skills" in system and "write-an-adr (/pmagent/agent-rules/skills/write-an-adr.md)" in system
    assert "Prefer primary sources." not in system  # the research agent's, not the PM's

    removed = await db_client.put(f"{ws}/rules/research", json={"content": "", "base_version": 1}, headers=ada.headers)
    assert removed.status_code == 200 and removed.json()["content"] == ""
    assert [r["handle"] for r in (await db_client.get(f"{ws}/rules", headers=cat.headers)).json()] == ["base"]
    actions = [e["action"] for e in (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()]
    assert actions.count("workspace_rules.saved") == 3


async def test_projects_have_skills(db_client: AsyncClient, signup, create_team, add_member) -> None:
    ada, _, _, base = await _world(db_client, signup, create_team, add_member)
    res = await db_client.get(f"{base}/knowledge/files/agent-rules/skills/triage-a-bug.md", headers=ada.headers)
    assert res.status_code == 200 and "Description:" in res.json()["content"]


async def test_automations_stop_at_the_workspace_s_daily_tokens(
    db_client: AsyncClient, signup, create_team, add_member, agent_script, db_session
) -> None:
    ada, _, _, base = await _world(db_client, signup, create_team, add_member)
    settings = db_client._transport.app.state.settings  # type: ignore[attr-defined]
    before, settings.automation_daily_tokens = settings.automation_daily_tokens, 1_000
    try:
        made = (await db_client.post(f"{base}/automations", json={
            "name": "Daily", "instructions": "Summarise.", "schedule_hour": 6,
        }, headers=ada.headers)).json()
        agent_script.say("One.", "Two.")
        url = f"{base}/automations/{made['id']}/run"
        assert (await db_client.post(url, headers=ada.headers)).json()["last_error"] is None
        await db_session.execute(update(AgentRun).values(input_tokens=900, output_tokens=200,
                                                         created_at=datetime.now(UTC)))
        await db_session.commit()
        skipped = (await db_client.post(url, headers=ada.headers)).json()
        assert "used their 1,000 tokens today" in skipped["last_error"] and skipped["runs_today"] == 1
    finally:
        settings.automation_daily_tokens = before
