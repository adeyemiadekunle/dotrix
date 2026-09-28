"""The context pack every agent run starts with: the project, its documents (with what each is
about), the board, recent decisions, and what changed since the conversation last ran."""
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.modules.knowledge.models import KnowledgeFile
from pmagent_engine.testing import tool_call


@pytest.fixture
def project(db_client: AsyncClient, create_team, signup):
    async def _make():
        ada = await signup()
        team = await create_team(ada.headers)
        created = (
            await db_client.post(
                f"/v1/workspaces/{team['id']}/projects",
                json={"key": "KUN", "name": "Kumove", "description": "Freight for Nigeria"},
                headers=ada.headers,
            )
        ).json()
        return ada, f"/v1/workspaces/{team['id']}/projects/{created['id']}"

    return _make


def system_prompt(model) -> str:
    """What the PM's model was told before the conversation (its system message)."""
    first = model.received[0]
    return next(str(m.content) for m in first if m.type == "system")


async def test_a_run_starts_with_the_project_map(project, db_client: AsyncClient, agent_script) -> None:
    ada, base = await project()
    kb = f"{base}/knowledge/files"
    put = await db_client.put(
        f"{kb}/requirements/drivers.md",
        json={"content": "# Driver requirements\n\nDrivers can work several zones at once.\n\n## Zones\n"},
        headers=ada.headers,
    )
    assert put.status_code == 200
    await db_client.put(f"{kb}/decisions/0001-zones.md", json={"content": "# ADR 1: Zones are a join table\n\nBecause."}, headers=ada.headers)
    due = (date.today() + timedelta(days=2)).isoformat()
    for fields in (
        {"title": "Multi-zone dispatch", "status": "in_progress"},
        {"title": "Lagos postcodes rejected", "type": "bug", "description": "Steps: …", "status": "blocked"},
        {"title": "Migrate driver_zone", "due": due},
    ):
        assert (await db_client.post(f"{base}/issues", json={"type": "task", **fields}, headers=ada.headers)).status_code == 201

    model = agent_script.say("Here's where things stand.")
    await db_client.post(f"{base}/agent/runs", json={"message": "Where are we?"}, headers=ada.headers)
    prompt = system_prompt(model)

    assert "## Using the project context" in prompt  # how to use it, before the pack itself
    assert "# Project context: Kumove (KUN)" in prompt
    assert "## Project (project.md)" in prompt
    # Every document with what it's about, not its content.
    assert "- requirements/drivers.md: **Driver requirements**: Drivers can work several zones at once. (v1," in prompt
    assert "agent-rules/" not in prompt.split("# Project context")[1]  # rules are in the instructions already
    # The board.
    assert "## Board (3 issues: 1 todo, 1 in progress, 1 blocked, 0 review, 0 done)" in prompt
    assert "- KUN-1 [in_progress, medium] Multi-zone dispatch (unassigned)" in prompt
    assert "- KUN-2 [blocked, medium] Lagos postcodes rejected" in prompt
    assert f"- KUN-3 [todo, medium, due {due}] Migrate driver_zone" in prompt
    # Recent decisions.
    assert "## Recent decisions\n- ADR 1: Zones are a join table (decisions/0001-zones.md," in prompt
    # A new conversation has no "since last time" section.
    assert "Since this conversation's last message" not in prompt


async def test_specialists_get_the_same_map(project, db_client: AsyncClient, agent_script) -> None:
    ada, base = await project()
    model = agent_script.say(
        tool_call("task", description="Summarise the vision", subagent_type="research-agent"),
        "The vision is freight.",  # the specialist
        "Research says: freight.",  # the PM
    )
    await db_client.post(f"{base}/agent/runs", json={"message": "Ask research"}, headers=ada.headers)
    specialist = next(str(m.content) for m in model.received[1] if m.type == "system")
    assert specialist.startswith("You are the Research Agent") or "Research Agent" in specialist
    assert "# Project context: Kumove (KUN)" in specialist


async def test_a_follow_up_hears_what_changed_meanwhile(project, db_client: AsyncClient, agent_script) -> None:
    ada, base = await project()
    agent_script.say("Noted.")
    first = (await db_client.post(f"{base}/agent/runs", json={"message": "Hi"}, headers=ada.headers)).json()
    # Meanwhile, someone edits a document and opens an issue.
    await db_client.put(f"{base}/knowledge/files/roadmap.md", json={"content": "# Roadmap\n\nPhase 1: zones."}, headers=ada.headers)
    await db_client.post(f"{base}/issues", json={"type": "task", "title": "Zones UI"}, headers=ada.headers)

    model = agent_script.say("I see the roadmap changed.")
    await db_client.post(
        f"{base}/agent/runs", json={"message": "What changed?", "thread_id": first["thread_id"]}, headers=ada.headers
    )
    prompt = system_prompt(model)
    assert "## Since this conversation's last message" in prompt
    assert "- roadmap.md: v2" in prompt
    assert "- KUN-1: created" in prompt


async def test_older_documents_are_described_when_first_needed(
    project, db_client: AsyncClient, agent_script, db_session: AsyncSession
) -> None:
    ada, base = await project()
    # As if written before descriptions existed.
    await db_session.execute(update(KnowledgeFile).values(title=None, summary=None, outline=[], described_version=None))
    await db_session.commit()
    model = agent_script.say("ok")
    await db_client.post(f"{base}/agent/runs", json={"message": "Hi"}, headers=ada.headers)
    assert "- project.md: **" in system_prompt(model)
    rows = (await db_session.execute(KnowledgeFile.__table__.select())).mappings().all()
    assert rows and all(r["described_version"] == r["version"] and r["title"] for r in rows)


async def test_the_pack_stays_small(project, db_client: AsyncClient, agent_script) -> None:
    ada, base = await project()
    for n in range(300):
        await db_client.put(
            f"{base}/knowledge/files/research/note-{n:03}.md",
            json={"content": f"# Note {n}\n\n" + "A long line of research findings. " * 12},
            headers=ada.headers,
        )
    model = agent_script.say("ok")
    await db_client.post(f"{base}/agent/runs", json={"message": "Hi"}, headers=ada.headers)
    pack = system_prompt(model).split("# Project context", 1)[1]
    assert len(pack) <= 24_100
    assert pack.rstrip().endswith("use ls or glob)")


async def test_a_briefing_hears_what_happened_since_the_last_one(project, db_client: AsyncClient, agent_script) -> None:
    ada, base = await project()
    model = agent_script.say("First briefing.")
    await db_client.post(f"{base}/agent/briefing", headers=ada.headers)
    assert "## In the last 7 days (the first briefing)" in system_prompt(model)

    # Then the work happens.
    issues = f"{base}/issues"
    for title in ("Zones UI", "Postcodes", "Driver app"):
        await db_client.post(issues, json={"type": "task", "title": title}, headers=ada.headers)
    await db_client.patch(f"{issues}/KUN-1", json={"status": "done"}, headers=ada.headers)
    await db_client.patch(f"{issues}/KUN-2", json={"status": "blocked"}, headers=ada.headers)
    await db_client.patch(f"{issues}/KUN-3", json={"status": "in_progress"}, headers=ada.headers)
    await db_client.post(f"{issues}/KUN-2/comments", json={"body": "Waiting on the postcode list"}, headers=ada.headers)
    await db_client.put(
        f"{base}/knowledge/files/roadmap.md", json={"content": "# Roadmap\n\nZones first.", "message": "Zones first"},
        headers=ada.headers,
    )

    model = agent_script.say("Second briefing.")
    await db_client.post(f"{base}/agent/briefing", headers=ada.headers)
    prompt = system_prompt(model)
    section = prompt.split("## Since the last briefing", 1)[1].split("\n## ", 1)[0]
    assert "Created: KUN-1 Zones UI; KUN-2 Postcodes; KUN-3 Driver app" in section
    assert "Done: KUN-1 Zones UI" in section
    assert "Newly blocked: KUN-2 Postcodes" in section
    assert "Moved: KUN-3 todo → in progress" in section
    assert "Discussed: KUN-2 (1 comment)" in section
    assert "- roadmap.md v2 by Ada: Zones first" in section
    assert "current-state.md was last changed" in section  # the written state fell behind
    # The briefing is told to write from this, not to explore.
    human = next(str(m.content) for m in model.received[0] if m.type == "human")
    assert "don't ask the specialists" in human
