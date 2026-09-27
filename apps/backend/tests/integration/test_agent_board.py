"""Agents on the issue board: reads are free, changes wait for approval, and the PRD's
per-agent rules decide who may create or edit what."""
import pytest
from httpx import AsyncClient

from pmagent_engine.testing import tool_call


@pytest.fixture
def project(db_client: AsyncClient, create_team, signup):
    async def _make():
        ada = await signup()
        team = await create_team(ada.headers)
        created = (
            await db_client.post(
                f"/v1/workspaces/{team['id']}/projects", json={"key": "KUN", "name": "Kunemi"},
                headers=ada.headers,
            )
        ).json()
        base = f"/v1/workspaces/{team['id']}/projects/{created['id']}"
        return ada, team, base

    return _make


async def run(client: AsyncClient, base: str, headers, message: str = "go") -> dict:
    res = await client.post(f"{base}/agent/runs", json={"message": message}, headers=headers)
    assert res.status_code == 202, res.text
    return res.json()


async def decide(client: AsyncClient, base: str, run_: dict, headers, decision: str = "approve", reason=None):
    pending = [a for a in run_["approvals"] if a["status"] == "pending"]
    body = {"decisions": [{"approval_id": a["id"], "decision": decision, "reason": reason} for a in pending]}
    res = await client.post(f"{base}/agent/runs/{run_['id']}/decisions", json=body, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def tool_results(model) -> list[str]:
    """Every tool result the agents saw (the scripted model records its prompts)."""
    return [str(m.content) for prompt in model.received for m in prompt if getattr(m, "type", "") == "tool"]


async def issues(client: AsyncClient, base: str, headers) -> list[dict]:
    return (await client.get(f"{base}/issues", headers=headers)).json()


async def test_reading_the_board_needs_no_approval(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    await db_client.post(f"{base}/issues", json={"title": "Hub model", "priority": "urgent"}, headers=ada.headers)
    model = agent_script.say(tool_call("list_issues", status="todo"), "One urgent issue: KUN-1 Hub model.")
    done = await run(db_client, base, ada.headers, "what's on the board?")
    assert done["status"] == "completed" and done["approvals"] == []
    assert "Hub model" in str(model.received[-1])  # the tool result reached the model


async def test_pm_creates_an_epic_after_approval(project, db_client: AsyncClient, agent_script) -> None:
    ada, team, base = await project()
    agent_script.say(
        tool_call("create_issue", type="epic", title="Scheduled delivery", description="Book a slot."),
        "Created KUN-1: Scheduled delivery.",
    )
    paused = await run(db_client, base, ada.headers, "create the scheduled delivery epic")
    assert paused["status"] == "awaiting_approval"
    [approval] = paused["approvals"]
    assert approval["tool"] == "create_issue" and approval["target"] == "new epic: Scheduled delivery"
    assert await issues(db_client, base, ada.headers) == []  # nothing before approval

    done = await decide(db_client, base, paused, ada.headers)
    assert done["status"] == "completed"
    [epic] = await issues(db_client, base, ada.headers)
    detail = (await db_client.get(f"{base}/issues/{epic['key']}", headers=ada.headers)).json()
    assert (detail["key"], detail["type"], detail["reporter_agent"]) == ("KUN-1", "epic", "project-manager")
    assert detail["log"][0]["author_agent"] == "project-manager"

    audit = (await db_client.get(f"/v1/workspaces/{team['id']}/audit", params={"action": "issue.create"}, headers=ada.headers)).json()
    assert audit[0]["agent"] == "project-manager"
    assert audit[0]["instructed_by_id"] == ada.id and audit[0]["approved_by_id"] == ada.id


async def test_specialists_open_only_their_issue_types(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    await db_client.post(f"{base}/issues", json={"type": "epic", "title": "Scheduled delivery"}, headers=ada.headers)
    model = agent_script.say(
        tool_call("task", description="Write the stories", subagent_type="product-agent"),
        # Product opens a story (allowed) and a bug (not its kind).
        tool_call("create_issue", call_id="story", type="story", title="Book a delivery slot",
                  description="Acceptance: merchant picks a slot.", parent="KUN-1"),
        tool_call("create_issue", call_id="bug", type="bug", title="Slots overlap", description="Repro: ..."),
        "Story written; bugs are the Reviewer's.",
        "Product added KUN-2.",
    )
    paused = await run(db_client, base, ada.headers, "have product write the stories")
    for _ in range(3):  # each write pauses; approve until the run finishes
        if paused["status"] != "awaiting_approval":
            break
        paused = await decide(db_client, base, paused, ada.headers)
    assert paused["status"] == "completed", paused

    created = {i["key"]: i for i in await issues(db_client, base, ada.headers)}
    assert set(created) == {"KUN-1", "KUN-2"}  # the bug was refused
    story = (await db_client.get(f"{base}/issues/KUN-2", headers=ada.headers)).json()
    assert (story["type"], story["parent_key"], story["reporter_agent"]) == ("story", "KUN-1", "product")
    assert any("The product agent can't open bug issues" in text for text in tool_results(model))


async def test_only_the_pm_edits_and_closes(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    await db_client.post(f"{base}/issues", json={"title": "Hub model", "status": "review"}, headers=ada.headers)
    model = agent_script.say(
        tool_call("task", description="Tidy KUN-1", subagent_type="architecture-agent"),
        tool_call("update_issue", key="KUN-1", priority="urgent"),
        "I can't edit issues.",
        # The PM closes the reviewed issue.
        tool_call("update_issue", key="KUN-1", status="done", note="Reviewed and accepted"),
        "Closed KUN-1.",
    )
    paused = await run(db_client, base, ada.headers, "close KUN-1 if it's reviewed")
    for _ in range(3):
        if paused["status"] != "awaiting_approval":
            break
        paused = await decide(db_client, base, paused, ada.headers)
    assert paused["status"] == "completed"
    issue = (await db_client.get(f"{base}/issues/KUN-1", headers=ada.headers)).json()
    assert issue["status"] == "done" and issue["priority"] == "medium"  # architecture's edit refused
    # Specialists aren't even given update_issue; the service refuses it too (see below).
    assert any("update_issue is not a valid tool" in text for text in tool_results(model))
    last = issue["log"][-1]
    assert last["author_agent"] == "project-manager" and last["body"] == "Reviewed and accepted"


async def test_rejected_board_change_is_not_applied(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    agent_script.say(tool_call("create_issue", type="task", title="Rewrite everything"), "OK, I won't.")
    paused = await run(db_client, base, ada.headers)
    done = await decide(db_client, base, paused, ada.headers, "reject", "Not now")
    assert done["status"] == "completed" and await issues(db_client, base, ada.headers) == []


async def test_briefing_never_changes_the_board(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    agent_script.say(tool_call("create_issue", type="task", title="Sneaky"), "Briefing: all quiet.")
    res = await db_client.post(f"{base}/agent/briefing", headers=ada.headers)
    assert res.json()["status"] == "completed" and await issues(db_client, base, ada.headers) == []


async def test_service_refuses_specialist_edits_even_without_the_tool(
    project, db_client: AsyncClient, db_session
) -> None:
    """Defence in depth: if a specialist were ever handed update_issue, the service still refuses."""
    import uuid

    from pmagent_backend.core.errors import Forbidden
    from pmagent_backend.modules.issues.schemas import IssueUpdate
    from pmagent_backend.modules.issues.service import IssueActor, IssueService
    from pmagent_backend.modules.projects.repository import ProjectRepository
    from pmagent_backend.modules.workspaces.repository import MembershipRepository

    ada, team, base = await project()
    await db_client.post(f"{base}/issues", json={"title": "Hub model"}, headers=ada.headers)
    project_id = uuid.UUID(base.rsplit("/", 1)[1])
    proj = await ProjectRepository(db_session).get(uuid.UUID(team["id"]), project_id)
    member = await MembershipRepository(db_session).get(uuid.UUID(team["id"]), uuid.UUID(ada.id))
    for role in ("architecture", "product", "research", "reviewer", "documentation"):
        actor = IssueActor(member, thinking_agent=role, approved_by_id=member.user_id)
        with pytest.raises(Forbidden):
            await IssueService(db_session).update(proj, "KUN-1", actor, IssueUpdate(priority="urgent"))
