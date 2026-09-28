"""Members chat and brainstorm; changing documents is for owners and admins, unless the
workspace grants members more (`member_permissions`)."""
from httpx import AsyncClient

from pmagent_backend.modules.workspaces.models import Role
from pmagent_engine.testing import tool_call


async def _team(db_client: AsyncClient, signup, create_team, add_member):
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    team = await create_team(ada.headers)
    await add_member(team["id"], bob.id, Role.MEMBER)
    project = (
        await db_client.post(f"/v1/workspaces/{team['id']}/projects", json={"key": "KUN", "name": "K"}, headers=ada.headers)
    ).json()
    return ada, bob, team, f"/v1/workspaces/{team['id']}/projects/{project['id']}"


async def test_what_members_can_do_by_default(db_client: AsyncClient, signup, create_team, add_member, agent_script) -> None:
    ada, bob, team, base = await _team(db_client, signup, create_team, add_member)
    ws = (await db_client.get(f"/v1/workspaces/{team['id']}", headers=bob.headers)).json()
    assert ws["member_permissions"] == []
    assert ws["permissions"] == ["workspace:view", "agents:chat", "issues:write"]
    owner = (await db_client.get(f"/v1/workspaces/{team['id']}", headers=ada.headers)).json()
    assert "agents:approve" in owner["permissions"] and "knowledge:write" in owner["permissions"]

    # Bob chats (and brainstorms); a change he asks for waits for an owner or admin.
    agent_script.say(tool_call("write_file", file_path="/pmagent/roadmap.md", content="# Bob's plan"), "Updated.")
    paused = (await db_client.post(f"{base}/agent/runs", json={"message": "Rewrite the roadmap"}, headers=bob.headers)).json()
    assert paused["status"] == "awaiting_approval"
    approval_id = paused["approvals"][0]["id"]
    decide = {"decisions": [{"approval_id": approval_id, "decision": "approve"}]}
    assert (await db_client.post(f"{base}/agent/runs/{paused['id']}/decisions", json=decide, headers=bob.headers)).status_code == 403
    # An owner decides it.
    done = await db_client.post(f"{base}/agent/runs/{paused['id']}/decisions", json=decide, headers=ada.headers)
    assert done.status_code == 200
    # Members still work the board.
    issue = await db_client.post(f"{base}/issues", json={"type": "task", "title": "Wire up zones"}, headers=bob.headers)
    assert issue.status_code == 201


async def test_owners_and_admins_grant_members_more(db_client: AsyncClient, signup, create_team, add_member) -> None:
    ada, bob, team, base = await _team(db_client, signup, create_team, add_member)
    ws = f"/v1/workspaces/{team['id']}"
    # Members can't change the setting themselves.
    assert (await db_client.patch(ws, json={"member_permissions": ["agents:approve"]}, headers=bob.headers)).status_code == 403
    # Only the grantable permissions are accepted.
    bad = await db_client.patch(ws, json={"member_permissions": ["members:manage"]}, headers=ada.headers)
    assert bad.status_code == 422
    granted = await db_client.patch(ws, json={"member_permissions": ["agents:approve", "knowledge:write", "agents:approve"]}, headers=ada.headers)
    assert granted.status_code == 200
    assert granted.json()["member_permissions"] == ["knowledge:write", "agents:approve"]
    assert granted.json()["name"] == team["name"]  # (the name wasn't sent: unchanged)
    mine = (await db_client.get(ws, headers=bob.headers)).json()["permissions"]
    assert "agents:approve" in mine and "knowledge:write" in mine and "agents:code" not in mine
    # The coding agent is grantable too.
    await db_client.patch(ws, json={"member_permissions": ["agents:code"]}, headers=ada.headers)
    issue = await db_client.post(f"{base}/issues", json={"type": "task", "title": "t", "assignee_agent": "coding-agent"}, headers=bob.headers)
    assert issue.status_code == 201
    # The change is in the audit log.
    audit = (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()
    changes = [e for e in audit if e["action"] == "workspace.member_permissions_changed"]
    assert changes[-1]["details"] == {"from": [], "to": ["agents:approve", "knowledge:write"]}


async def test_grants_never_reach_guests(db_client: AsyncClient, signup, create_team, add_member) -> None:
    ada, _, team, _ = await _team(db_client, signup, create_team, add_member)
    guest = await signup(email="guest@example.com", name="Guest")
    await add_member(team["id"], guest.id, Role.GUEST)
    await db_client.patch(f"/v1/workspaces/{team['id']}", json={"member_permissions": ["knowledge:write", "agents:approve"]}, headers=ada.headers)
    theirs = (await db_client.get(f"/v1/workspaces/{team['id']}", headers=guest.headers)).json()["permissions"]
    assert theirs == ["workspace:view"]
