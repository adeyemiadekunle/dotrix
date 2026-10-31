"""Rules that layer (agents v2 step 2): workspace rules under each project's, and skills."""
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import update

from dotrix_backend.modules.agents.models import AgentRun
from dotrix_backend.modules.workspaces.models import Role


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
    assert "## Skills" in system and "- write-an-adr: Record an architecture decision" in system
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


async def test_workspace_skills_are_shared_and_a_project_s_own_wins(
    db_client: AsyncClient, signup, create_team, add_member, agent_script
) -> None:
    from dotrix_engine.testing import tool_call

    ada, cat, ws, base = await _world(db_client, signup, create_team, add_member)
    note = {"content": "Description: Write the release note.\n\n1. List what changed.", "base_version": 0}
    assert (await db_client.put(f"{ws}/skills/release-note", json=note, headers=cat.headers)).status_code == 403
    saved = await db_client.put(f"{ws}/skills/release-note", json=note, headers=ada.headers)
    assert saved.status_code == 200 and saved.json()["description"] == "Write the release note."
    assert (await db_client.put(f"{ws}/skills/release-note", json=note, headers=ada.headers)).status_code == 409
    assert (await db_client.put(f"{ws}/skills/Bad_Name", json=note, headers=ada.headers)).status_code == 422
    # The workspace shares one called write-an-adr too: the project's own (seeded) wins.
    await db_client.put(f"{ws}/skills/write-an-adr", headers=ada.headers,
                        json={"content": "Description: The workspace's way.", "base_version": 0})
    assert [s["name"] for s in (await db_client.get(f"{ws}/skills", headers=cat.headers)).json()] == [
        "release-note", "write-an-adr"
    ]

    model = agent_script.say(
        tool_call("read_skill", skill="release-note"), tool_call("read_skill", skill="write-an-adr"), "Done.",
    )
    await db_client.post(f"{base}/agent/runs", json={"message": "write the release note"}, headers=ada.headers)
    system = model.received[0][0].content
    assert "- release-note: Write the release note." in system
    assert "- write-an-adr: Record an architecture decision" in system and "The workspace's way" not in system
    results = [m.content for m in model.received[-1] if getattr(m, "name", None) == "read_skill"]
    assert results[0].startswith("Skill release-note (the workspace's)") and "List what changed" in results[0]
    assert results[1].startswith("Skill write-an-adr (this project's)")

    gone = await db_client.put(f"{ws}/skills/release-note", json={"content": "", "base_version": 1}, headers=ada.headers)
    assert gone.status_code == 200
    assert [s["name"] for s in (await db_client.get(f"{ws}/skills", headers=cat.headers)).json()] == ["write-an-adr"]


async def test_each_agent_lists_its_own_skills(
    db_client: AsyncClient, signup, create_team, add_member, agent_script
) -> None:
    from dotrix_backend.modules.agents.guidance import project_rules
    from dotrix_backend.modules.projects.models import Project

    ada, _, ws, base = await _world(db_client, signup, create_team, add_member)
    await db_client.put(f"{base}/knowledge/files/agent-rules/skills/team-checklist.md", headers=ada.headers,
                        json={"content": "# Skill\nDescription: Our own checklist, for everyone.\n"})
    factory = db_client._transport.app.state.jobs.ctx.session_factory  # type: ignore[attr-defined]
    async with factory() as session:
        project = await session.get(Project, base.rsplit("/", 1)[-1])
        rules = await project_rules(session, project.id, None, project.workspace_id)
    assert "- team-checklist: Our own checklist" in rules["base"]  # no Agents line: every agent's
    assert "security-review" not in rules["base"]
    assert "- security-review:" in rules["reviewer"] and "- threat-model-a-feature:" in rules["architecture"]
    assert "- write-acceptance-criteria:" in rules["product"] and "security-review" not in rules["product"]
    assert "- evaluate-a-library:" in rules["research"] and "- keep-the-wiki-fresh:" in rules["documentation"]
    assert "- definition-of-done:" in rules["reviewer"]


async def test_kai_s_brief_carries_the_definition_of_done_its_skills_and_the_team_s_coding_rules(
    db_client: AsyncClient, signup, create_team, add_member, agent_script
) -> None:
    from dotrix_backend.modules.coding.brief import build_brief
    from dotrix_backend.modules.projects.models import Project

    ada, _, ws, base = await _world(db_client, signup, create_team, add_member)
    issue = (await db_client.post(f"{base}/issues", headers=ada.headers, json={
        "type": "task", "title": "Add a login page", "description": "A form for the email and password."})).json()
    typo = (await db_client.post(f"{base}/issues", headers=ada.headers, json={"type": "task", "title": "Fix a typo in the README"})).json()
    factory = db_client._transport.app.state.jobs.ctx.session_factory  # type: ignore[attr-defined]
    saved = await db_client.put(f"{base}/knowledge/files/agent-rules/coding.md", headers=ada.headers,
                                json={"content": "# Coding\nUse the repository's logger, never print()."})
    assert saved.status_code in (200, 201), saved.text
    from dotrix_backend.modules.issues.schemas import IssueRead

    async with factory() as session:
        project = await session.get(Project, base.rsplit("/", 1)[-1])
        brief = await build_brief(session, project, IssueRead.model_validate(issue), None)
    assert "## Definition of done" in brief and "migration can be rolled back" in brief
    assert "Use the repository's logger, never print()." in brief  # the project's own coding rules
    # The skills this issue calls for (a login form: security and UI), not every one of Kai's.
    assert '<data source="skill security-review">' in brief and '<data source="skill build-a-ui-change">' in brief
    assert "skill plan-a-schema-change" not in brief and "skill design-an-api" not in brief
    assert "skill definition-of-done" not in brief  # the list itself is in the brief
    assert "write-acceptance-criteria" not in brief  # Lyra's, not Kai's
    async with factory() as session:
        project = await session.get(Project, base.rsplit("/", 1)[-1])
        plain = await build_brief(session, project, IssueRead.model_validate(typo), None)
    assert "## Definition of done" in plain and "## Skills for this work" not in plain
    assert "Open a pull request that links" not in brief  # the engine's default coding.md isn't repeated
