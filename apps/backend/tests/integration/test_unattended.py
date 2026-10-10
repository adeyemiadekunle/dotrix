"""Agents acting without approval: an owner's standing rule in the agent's contract, and every
guard around it (the workspace pause, briefings, automations' own switch, the instructing
person's rights, closing issues, folder access, the caps)."""
import uuid

import pytest
from httpx import AsyncClient

from dotrix_backend.modules.agents.unattended import Unattended, effective_specs
from dotrix_backend.modules.workspaces.models import Membership, Role
from dotrix_engine.contracts import AgentPolicy, AgentSpec
from dotrix_engine.testing import tool_call

WRITER = {
    "name": "Writer",
    "description": "Keeps the reviews and the board current.",
    "instructions": "Write reviews and keep the board current.",
    "tools": ["knowledge.read", "knowledge.write", "board.read", "issues.create", "issues.update"],
    "access": {"reviews/*": "write"},
    "issue_types": ["bug"],
    "autonomy": {"knowledge.write": "allow", "issues.create": "allow", "issues.update": "allow"},
}


@pytest.fixture
def world(db_client: AsyncClient, create_team, signup, add_member):
    """Ada owns a team with project KUN and a Writer agent allowed to act unasked; Bob is an
    admin, Cat a member."""

    async def _make():
        ada = await signup()
        bob = await signup(email="bob@example.com", name="Bob")
        cat = await signup(email="cat@example.com", name="Cat")
        team = await create_team(ada.headers)
        await add_member(team["id"], bob.id, Role.ADMIN)
        await add_member(team["id"], cat.id, Role.MEMBER)
        ws = f"/v1/workspaces/{team['id']}"
        project = (await db_client.post(f"{ws}/projects", json={"key": "KUN", "name": "Kunemi"},
                                        headers=ada.headers)).json()
        saved = await db_client.put(f"{ws}/agents/writer", json={"agent": WRITER}, headers=ada.headers)
        assert saved.status_code == 200, saved.text
        return ada, bob, cat, ws, f"{ws}/projects/{project['id']}"

    return _make


async def _ask(client: AsyncClient, base: str, headers, message: str = "do it") -> dict:
    return (await client.post(f"{base}/agent/runs", json={"message": message, "agent": "writer"},
                              headers=headers)).json()


async def test_allowed_changes_go_through_recorded_as_the_owner_s_rule(
    world, db_client: AsyncClient, agent_script
) -> None:
    ada, bob, _, ws, base = await world()
    issue = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Rotate keys"},
                                  headers=ada.headers)).json()
    agent_script.say(
        tool_call("write_file", file_path="/dotrix/reviews/auth.md", content="# Auth review\n"),
        tool_call("write_file", file_path="/dotrix/requirements/auth.md", content="# Not mine\n"),
        tool_call("create_issue", type="bug", title="Token in logs", description="auth.py logs it"),
        tool_call("update_issue", key=issue["key"], status="in_progress"),
        tool_call("update_issue", key=issue["key"], status="done"),
        "Done.",
    )
    run = await _ask(db_client, base, bob.headers)
    assert run["status"] == "completed", run  # nothing waited for a person
    assert not run["approvals"]
    # Told what it may change unasked.
    assert "What you may change without asking" in str(agent_script.model.received[0][0].content)

    history = (await db_client.get(f"{base}/knowledge/files/reviews/auth.md/versions", headers=ada.headers)).json()
    assert history[0]["agent"] == "writer" and history[0]["approved_by_id"] == ada.id
    assert history[0]["instructed_by_id"] == bob.id
    # Folder access still applies.
    assert (await db_client.get(f"{base}/knowledge/files/requirements/auth.md", headers=ada.headers)).status_code == 404
    titles = [i["title"] for i in (await db_client.get(f"{base}/issues", headers=ada.headers)).json()]
    assert "Token in logs" in titles
    # Moved along, but closing it is a person's call.
    assert (await db_client.get(f"{base}/issues/{issue['key']}", headers=ada.headers)).json()["status"] == "in_progress"

    audit = (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()
    allowed = {e["action"] for e in audit if e["action"].endswith(".allowed")}
    assert allowed == {"knowledge.write.allowed", "issues.create.allowed", "issues.update.allowed"}
    write = next(e for e in audit if e["action"] == "knowledge.write.allowed")
    assert write["approved_by_id"] == ada.id and write["details"]["rule"] == {
        "agent": "writer", "action": "knowledge.write", "version": 1,
    }


async def test_paused_workspace_and_a_member_s_request_wait_for_approval(
    world, db_client: AsyncClient, agent_script
) -> None:
    ada, bob, cat, ws, base = await world()
    write = tool_call("write_file", file_path="/dotrix/reviews/a.md", content="# A\n")

    # Cat can't edit documents herself, so the agent doesn't do it unasked for her.
    agent_script.say(write, "Done.")
    assert (await _ask(db_client, base, cat.headers))["status"] == "awaiting_approval"

    # Admins pause; only owners resume.
    assert (await db_client.patch(ws, json={"unattended_paused": True}, headers=cat.headers)).status_code == 403
    paused = await db_client.patch(ws, json={"unattended_paused": True}, headers=bob.headers)
    assert paused.status_code == 200 and paused.json()["unattended_paused"] is True
    agent_script.say(write, "Done.")
    assert (await _ask(db_client, base, ada.headers))["status"] == "awaiting_approval"
    assert (await db_client.patch(ws, json={"unattended_paused": False}, headers=bob.headers)).status_code == 403
    assert (await db_client.patch(ws, json={"unattended_paused": False}, headers=ada.headers)).status_code == 200

    actions = [e["action"] for e in (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()]
    assert {"workspace.unattended_paused", "workspace.unattended_resumed"} <= set(actions)


async def test_an_automation_acts_unasked_only_with_its_own_switch(
    world, db_client: AsyncClient, agent_script
) -> None:
    ada, bob, _, _, base = await world()
    made = (await db_client.post(f"{base}/automations", json={
        "name": "Reviews", "agent": "writer", "instructions": "Write the review.", "schedule_hour": 6,
    }, headers=ada.headers)).json()
    assert made["unattended"] is False
    url = f"{base}/automations/{made['id']}"

    agent_script.say(tool_call("write_file", file_path="/dotrix/reviews/a.md", content="# A\n"), "Done.")
    await db_client.post(f"{url}/run", headers=ada.headers)
    runs = (await db_client.get(f"{base}/agent/runs", headers=ada.headers)).json()
    assert runs[0]["status"] == "awaiting_approval"
    pending = [a for a in (await db_client.get(f"{base}/agent/runs/{runs[0]['id']}", headers=ada.headers)).json()["approvals"]]
    await db_client.post(f"{base}/agent/runs/{runs[0]['id']}/decisions", headers=ada.headers,
                         json={"decisions": [{"approval_id": a["id"], "decision": "reject"} for a in pending]})

    # Admins can't switch it on; owners can.
    assert (await db_client.patch(url, json={"unattended": True}, headers=bob.headers)).status_code == 403
    assert (await db_client.patch(url, json={"unattended": True}, headers=ada.headers)).json()["unattended"] is True
    agent_script.say(tool_call("write_file", file_path="/dotrix/reviews/b.md", content="# B\n"), "Done.")
    await db_client.post(f"{url}/run", headers=ada.headers)
    runs = (await db_client.get(f"{base}/agent/runs", headers=ada.headers)).json()
    assert runs[0]["status"] == "completed", runs[0]
    assert (await db_client.get(f"{base}/knowledge/files/reviews/b.md", headers=ada.headers)).status_code == 200


def _member(role: Role, permissions: list[str] | None = None) -> Membership:
    from dotrix_backend.modules.workspaces.models import Workspace

    member = Membership(user_id=uuid.uuid4(), role=role)
    member.workspace = Workspace(member_permissions=permissions or [])
    return member


def test_what_a_run_may_use_and_the_cap() -> None:
    spec = AgentSpec.model_validate(WRITER | {"handle": "writer"} | {
        "tools": [*WRITER["tools"], "issues.comment"],
        "autonomy": WRITER["autonomy"] | {"issues.comment": "allow"},
    })
    owner, admin = _member(Role.OWNER), _member(Role.ADMIN)

    def allows(**kw) -> list[str]:
        args = {"authors": {"writer": owner}, "instructor": owner, "paused": False, "briefing": False,
                "automation": None} | kw
        return effective_specs([spec], **args)[0].allows()

    everything = ["knowledge.write", "issues.create", "issues.update", "issues.comment"]
    assert allows() == everything
    assert allows(paused=True) == [] and allows(briefing=True) == []
    assert allows(automation=False) == ["issues.comment"]  # the low-risk ones only
    assert allows(automation=True) == everything
    # The version's author is no longer an owner: only the low-risk ones stand.
    assert allows(authors={"writer": admin}) == ["issues.comment"]
    assert allows(authors={}) == []
    # A member who can't edit documents doesn't get documents written unasked.
    assert allows(instructor=_member(Role.MEMBER)) == ["issues.create", "issues.update", "issues.comment"]

    approver = uuid.uuid4()
    unattended = Unattended(AgentPolicy([spec]), {"writer": approver}, {"writer": 3}, left=2)
    assert unattended.grant("writer", "issues.create") == (approver, {"agent": "writer", "action": "issues.create", "version": 3})
    assert isinstance(unattended.grant("writer", "issues.update"), tuple)
    assert "limit of 2" in unattended.grant("writer", "issues.update")  # type: ignore[operator]
    assert "approval" in Unattended(AgentPolicy([spec]), {}, {}, left=5).grant("writer", "issues.create")  # type: ignore[operator]


async def test_always_allow_from_a_waiting_change(world, db_client: AsyncClient, agent_script) -> None:
    ada, bob, _, ws, base = await world()
    # Lyra (product) asks before writing; owners can turn that into a standing rule from the change.
    agent_script.say(tool_call("write_file", file_path="/dotrix/requirements/a.md", content="# A\n"), "Done.")
    run = (await db_client.post(f"{base}/agent/runs", json={"message": "write it", "agent": "product"},
                                headers=ada.headers)).json()
    change = run["approvals"][0]
    assert run["status"] == "awaiting_approval"
    assert change["agent"] == "product" and change["action"] == "knowledge.write"
    url = f"{base}/agent/runs/{run['id']}/approvals/{change['id']}/always-allow"

    assert (await db_client.post(url, headers=bob.headers)).status_code == 403  # admins can't
    allowed = await db_client.post(url, headers=ada.headers)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["autonomy"] == {"knowledge.write": "allow"} and allowed.json()["source"] == "customised"
    history = (await db_client.get(f"{ws}/agents/product/versions", headers=ada.headers)).json()
    assert history[0]["note"].startswith("Always allow knowledge.write")
    # The change itself still waits; the next one goes straight through.
    assert (await db_client.get(f"{base}/agent/runs/{run['id']}", headers=ada.headers)).json()["status"] == "awaiting_approval"
    agent_script.say(tool_call("write_file", file_path="/dotrix/requirements/b.md", content="# B\n"), "Done.")
    second = (await db_client.post(f"{base}/agent/runs", json={"message": "and b", "agent": "product"},
                                   headers=ada.headers)).json()
    assert second["status"] == "completed", second

    # An id that isn't one of this run's changes is 404.
    assert (await db_client.post(f"{base}/agent/runs/{run['id']}/approvals/{uuid.uuid4()}/always-allow",
                                 headers=ada.headers)).status_code == 404


async def test_a_project_override_gets_the_rule_not_the_workspace(world, db_client: AsyncClient, agent_script) -> None:
    ada, _, _, ws, base = await world()
    product = (await db_client.get(f"{ws}/agents/product", headers=ada.headers)).json()
    fields = {k: product[k] for k in ("name", "description", "instructions", "tools", "access", "issue_types", "can_call")}
    assert (await db_client.put(f"{base}/agents/product", json={"agent": fields | {"description": "Ours."}},
                                headers=ada.headers)).status_code == 200
    agent_script.say(tool_call("write_file", file_path="/dotrix/requirements/a.md", content="# A\n"), "Done.")
    run = (await db_client.post(f"{base}/agent/runs", json={"message": "write it", "agent": "product"},
                                headers=ada.headers)).json()
    url = f"{base}/agent/runs/{run['id']}/approvals/{run['approvals'][0]['id']}/always-allow"
    saved = (await db_client.post(url, headers=ada.headers)).json()
    assert saved["scope"] == "project" and saved["autonomy"] == {"knowledge.write": "allow"}
    assert (await db_client.get(f"{ws}/agents/product", headers=ada.headers)).json()["autonomy"] == {}
