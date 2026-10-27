"""Agents as data: built-ins that owners change, custom agents, project overrides, and runs
that use them (docs/agents-v2.md §4)."""
import pytest
from httpx import AsyncClient

from dotrix_backend.modules.workspaces.models import Role
from dotrix_engine.testing import tool_call

SECURITY = {
    "name": "Security reviewer",
    "description": "Reviews changes for security risks.",
    "instructions": "Look for leaked secrets and unsafe defaults.",
    "tools": ["knowledge.read", "knowledge.search", "knowledge.write", "board.read", "issues.create"],
    "access": {"reviews/security/*": "write"},
    "issue_types": ["bug"],
}


@pytest.fixture
def world(db_client: AsyncClient, create_team, signup, add_member):
    """Ada owns a team with project KUN; Bob is an admin, Cat a member."""

    async def _make():
        ada = await signup()
        bob = await signup(email="bob@example.com", name="Bob")
        cat = await signup(email="cat@example.com", name="Cat")
        team = await create_team(ada.headers)
        await add_member(team["id"], bob.id, Role.ADMIN)
        await add_member(team["id"], cat.id, Role.MEMBER)
        project = (await db_client.post(f"/v1/workspaces/{team['id']}/projects", json={"key": "KUN", "name": "Kunemi"},
                                        headers=ada.headers)).json()
        ws = f"/v1/workspaces/{team['id']}"
        return ada, bob, cat, ws, f"{ws}/projects/{project['id']}"

    return _make


async def save(client: AsyncClient, url: str, headers, agent: dict, **extra):
    return await client.put(url, json={"agent": agent, **extra}, headers=headers)


async def test_the_builtins_are_listed_until_someone_changes_them(world, db_client: AsyncClient) -> None:
    ada, _, cat, ws, _ = await world()
    agents = (await db_client.get(f"{ws}/agents", headers=cat.headers)).json()
    assert [a["handle"] for a in agents] == [
        "project-manager", "product", "architecture", "research", "reviewer", "documentation"
    ]
    assert all(a["source"] == "built_in" and a["version"] is None for a in agents)
    research = next(a for a in agents if a["handle"] == "research")
    assert "spike" in research["issue_types"] and "web.search" in research["tools"]
    catalog = (await db_client.get(f"{ws}/agents/catalog", headers=cat.headers)).json()
    assert "knowledge.write" in {t["id"] for t in catalog["tools"]} and catalog["low_risk_actions"] == ["graph.link", "issues.comment"]


async def test_customise_a_builtin_then_reset_it(world, db_client: AsyncClient, agent_script) -> None:
    ada, _, _, ws, base = await world()
    product = (await db_client.get(f"{ws}/agents/product", headers=ada.headers)).json()
    fields = {k: product[k] for k in ("name", "description", "instructions", "tools", "access", "issue_types", "can_call")}
    changed = await save(db_client, f"{ws}/agents/product", ada.headers,
                         fields | {"additional_instructions": "Write every story as a job to be done."}, note="JTBD")
    assert changed.status_code == 200, changed.text
    assert changed.json()["source"] == "customised" and changed.json()["version"] == 1

    # A run led by the product agent uses the new instructions.
    model = agent_script.say("Here are the stories.")
    run = (await db_client.post(f"{base}/agent/runs", json={"message": "stories?", "agent": "product"},
                                headers=ada.headers)).json()
    assert run["status"] == "completed"
    assert "You are Nova" in str(model.received[0][0].content)

    # Stale edits are refused; saving the same thing again is a no-op.
    stale = await save(db_client, f"{ws}/agents/product", ada.headers, fields, base_version=0)
    assert stale.status_code == 409 and stale.json()["type"].endswith("/agent_changed")
    same = await save(db_client, f"{ws}/agents/product", ada.headers,
                      fields | {"additional_instructions": "Write every story as a job to be done."}, base_version=1)
    assert same.json()["version"] == 1

    assert (await db_client.delete(f"{ws}/agents/product", headers=ada.headers)).status_code == 204
    reset = (await db_client.get(f"{ws}/agents/product", headers=ada.headers)).json()
    assert reset["source"] == "built_in" and reset["instructions"] == product["instructions"]
    history = (await db_client.get(f"{ws}/agents/product/versions", headers=ada.headers)).json()
    assert [(v["version"], v["note"]) for v in history] == [(1, "JTBD")]
    restored = (await db_client.post(f"{ws}/agents/product/versions/1/restore", headers=ada.headers)).json()
    assert restored["version"] == 2 and restored["additional_instructions"].startswith("Write every story")

    actions = [e["action"] for e in (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()]
    assert {"agent.customised", "agent.reset"} <= set(actions)


async def test_custom_agents_cannot_be_created_or_executed(world, db_client: AsyncClient) -> None:
    ada, _, _, ws, base = await world()
    created = await save(db_client, f"{ws}/agents/security", ada.headers, SECURITY)
    assert created.status_code == 422 and "no longer supported" in created.json()["detail"]
    assert "security" not in [a["handle"] for a in (await db_client.get(f"{ws}/agents", headers=ada.headers)).json()]
    unknown = await db_client.post(f"{base}/agent/runs", json={"message": "review", "agent": "security"}, headers=ada.headers)
    assert unknown.status_code == 422 and unknown.json()["type"].endswith("/unknown_agent")
    assert (await db_client.post(f"{ws}/agents/security/versions/1/restore", headers=ada.headers)).status_code == 422


async def test_who_may_change_agents(world, db_client: AsyncClient) -> None:
    ada, bob, cat, ws, _ = await world()
    fields = (await db_client.get(f"{ws}/agents/project-manager", headers=ada.headers)).json()
    assert (await save(db_client, f"{ws}/agents/project-manager", cat.headers, fields)).status_code == 403
    fields["additional_instructions"] = "Use our terminology"
    assert (await save(db_client, f"{ws}/agents/project-manager", bob.headers, fields)).status_code == 200
    fields["autonomy"] = {"issues.comment": "allow"}
    assert (await save(db_client, f"{ws}/agents/project-manager", bob.headers, fields, base_version=1)).status_code == 403
    assert (await save(db_client, f"{ws}/agents/project-manager", ada.headers, fields, base_version=1)).status_code == 200
    fields["additional_instructions"] = "Keep comments concise"
    assert (await save(db_client, f"{ws}/agents/project-manager", bob.headers, fields, base_version=2)).status_code == 200
    fields["autonomy"]["issues.create"] = "allow"
    assert (await save(db_client, f"{ws}/agents/project-manager", ada.headers, fields, base_version=3)).status_code == 200
    fields["additional_instructions"] = "Another revision"
    assert (await save(db_client, f"{ws}/agents/project-manager", bob.headers, fields, base_version=4)).status_code == 403


@pytest.mark.parametrize("patch,message", [
    ({"instructions": "Replace the role"}, "read-only"),
    ({"access": {"agent-rules/*": "write"}}, "agent-rules"),
    ({"tools": ["shell"]}, "core role"),
    ({"can_call": ["security"]}, "built-in specialists"),
])
async def test_contracts_are_checked(world, db_client: AsyncClient, patch: dict, message: str) -> None:
    ada, _, _, ws, _ = await world()
    fields = (await db_client.get(f"{ws}/agents/product", headers=ada.headers)).json()
    response = await save(db_client, f"{ws}/agents/product", ada.headers, fields | patch)
    assert response.status_code == 422 and message in response.json()["detail"], response.text


async def test_workspace_and_project_guidance_compose_without_replacing_the_role(world, db_client: AsyncClient, db_session) -> None:
    from uuid import UUID

    from dotrix_backend.modules.agent_definitions.repository import AgentDefinitionRepository
    ada, _, _, ws, base = await world()
    research = (await db_client.get(f"{ws}/agents/research", headers=ada.headers)).json()
    saved = await save(db_client, f"{ws}/agents/research", ada.headers, research | {"additional_instructions": "Workspace conventions"})
    assert saved.status_code == 200
    override = await save(db_client, f"{base}/agents/research", ada.headers, research | {"additional_instructions": "Only cite EU sources."})
    assert override.status_code == 200 and override.json()["additional_instructions"] == "Only cite EU sources."
    effective = next(a.spec for a in await AgentDefinitionRepository(db_session).resolve(UUID(ws.rsplit('/',1)[1]), UUID(base.rsplit('/',1)[1])) if a.spec.handle == "research")
    assert effective.instructions == research["instructions"]
    assert effective.additional_instructions == "Workspace conventions\n\nOnly cite EU sources."
    unchanged = await save(db_client, f"{base}/agents/research", ada.headers, override.json(), base_version=1)
    assert unchanged.status_code == 200
    reread = (await db_client.get(f"{base}/agents/research", headers=ada.headers)).json()
    assert reread["additional_instructions"] == "Only cite EU sources."
    assert (await db_client.delete(f"{base}/agents/research", headers=ada.headers)).status_code == 204
    assert (await db_client.get(f"{base}/agents/research", headers=ada.headers)).json()["additional_instructions"] == "Workspace conventions"


async def test_an_allowed_comment_needs_no_approval_and_a_blocked_action_is_gone(
    world, db_client: AsyncClient, agent_script
) -> None:
    ada, _, _, ws, base = await world()
    issue = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Rotate keys"}, headers=ada.headers)).json()
    triage = (await db_client.get(f"{ws}/agents/project-manager", headers=ada.headers)).json()
    triage["autonomy"] = {"issues.comment": "allow", "issues.create": "block"}
    assert (await save(db_client, f"{ws}/agents/project-manager", ada.headers, triage)).status_code == 200

    agent_script.say(
        tool_call("comment_issue", key=issue["key"], text="Looks like a duplicate of nothing."),
        tool_call("create_issue", type="bug", title="Should not exist"),
        "Commented.",
    )
    done = (await db_client.post(f"{base}/agent/runs", json={"message": "triage it", "agent": "auto"},
                                 headers=ada.headers)).json()
    assert done["status"] == "completed", done  # nothing paused for approval
    log = (await db_client.get(f"{base}/issues/{issue['key']}", headers=ada.headers)).json()["log"]
    comment = next(e for e in log if e["kind"] == "commented")
    assert comment["author_agent"] == "project-manager" and "duplicate" in comment["body"]
    titles = [i["title"] for i in (await db_client.get(f"{base}/issues", headers=ada.headers)).json()]
    assert "Should not exist" not in titles  # blocked: it had no create tool
    audit = (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()
    allowed = next(e for e in audit if e["action"] == "issues.comment.allowed")
    assert allowed["agent"] == "project-manager" and allowed["details"]["rule"] == {"agent": "project-manager", "action": "issues.comment", "version": 1}


async def test_a_run_records_its_result_and_people_act_on_each_item(world, db_client: AsyncClient, agent_script) -> None:
    ada, _, cat, ws, base = await world()
    issue = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Review auth"}, headers=ada.headers)).json()
    agent_script.say(
        tool_call("stage", current="issue"),
        tool_call("submit_result", items=[
            {"severity": "high", "title": "Token in logs", "detail": "auth.py logs the refresh token", "refs": ["auth.py"]},
            {"severity": "low", "title": "Verbose errors", "detail": "Stack traces reach the client"},
        ]),
        "Two findings.",
    )
    done = (await db_client.post(f"{base}/agent/issues/{issue['key']}/review", headers=ada.headers)).json()
    assert done["status"] == "completed", done
    [output] = done["outputs"]
    assert output["agent"] == "reviewer" and output["kind"] == "finding" and "create_issue" in output["actions"]
    assert [i["data"]["title"] for i in output["items"]] == ["Token in logs", "Verbose errors"]
    assert all(i["state"] == "open" for i in output["items"])

    url = f"{base}/agent/runs/{done['id']}/outputs/{output['id']}/items"
    # The run is Ada's: a colleague doesn't see it, so can't act on it.
    assert (await db_client.patch(f"{url}/1", json={"state": "dismissed"}, headers=cat.headers)).status_code == 404
    dismissed = await db_client.patch(f"{url}/1", json={"state": "dismissed", "reason": "Dev only"}, headers=ada.headers)
    assert dismissed.status_code == 200, dismissed.text
    item = dismissed.json()["outputs"][0]["items"][1]
    assert item["state"] == "dismissed" and item["reason"] == "Dev only" and item["acted_by_id"] == ada.id
    marked = (await db_client.patch(f"{url}/0", json={"state": "done", "link": "KUN-7"}, headers=ada.headers)).json()
    assert marked["outputs"][0]["items"][0]["link"] == "KUN-7"
    assert (await db_client.patch(f"{url}/9", json={"state": "done"}, headers=ada.headers)).status_code == 404
    actions = [e["action"] for e in (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()]
    assert {"agent_output.dismissed", "agent_output.done"} <= set(actions)
