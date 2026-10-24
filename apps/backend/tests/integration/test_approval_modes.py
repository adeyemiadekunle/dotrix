"""Approval modes in a workspace: the cap its owners set, and what a person's mode lets go through.
Coding runs that start at once under Accept edits are in test_coding.py."""
from httpx import AsyncClient

from dotrix_backend.modules.workspaces.models import Role
from dotrix_engine.testing import tool_call


async def _team(db_client: AsyncClient, signup, create_team, add_member):
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    cat = await signup(email="cat@example.com", name="Cat")
    team = await create_team(ada.headers)
    await add_member(team["id"], bob.id, Role.ADMIN)
    await add_member(team["id"], cat.id, Role.MEMBER)
    ws = f"/v1/workspaces/{team['id']}"
    project = (await db_client.post(f"{ws}/projects", json={"key": "KUN", "name": "K"}, headers=ada.headers)).json()
    return ada, bob, cat, ws, f"{ws}/projects/{project['id']}"


async def test_the_workspace_s_cap_owners_raise_it_admins_lower_it(
    db_client: AsyncClient, signup, create_team, add_member
) -> None:
    ada, bob, _, ws, _ = await _team(db_client, signup, create_team, add_member)
    org = (await db_client.get(ws, headers=ada.headers)).json()
    assert (org["approval_mode_cap"], org["default_approval_mode"]) == ("manual", "manual")
    personal = (await db_client.get("/v1/workspaces", headers=ada.headers)).json()
    mine = next(w for w in personal if w["kind"] == "personal")
    assert (mine["approval_mode_cap"], mine["default_approval_mode"]) == ("auto", "accept_edits")

    assert (await db_client.patch(ws, json={"approval_mode_cap": "auto"}, headers=bob.headers)).status_code == 403
    raised = await db_client.patch(ws, json={"approval_mode_cap": "auto"}, headers=ada.headers)
    assert raised.status_code == 200 and raised.json()["approval_mode_cap"] == "auto"
    assert raised.json()["default_approval_mode"] == "manual"  # an organisation still starts on Manual
    lowered = await db_client.patch(ws, json={"approval_mode_cap": "accept_edits"}, headers=bob.headers)
    assert lowered.json()["approval_mode_cap"] == "accept_edits"
    # Pausing changes without approval puts everyone back on Manual.
    paused = await db_client.patch(ws, json={"unattended_paused": True}, headers=bob.headers)
    assert paused.json()["approval_mode_cap"] == "manual"
    audit = [e for e in (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()
             if e["action"] == "workspace.approval_mode_cap_changed"]
    assert sorted(e["details"]["to"] for e in audit) == ["accept_edits", "auto"]


async def test_accept_edits_lets_what_you_ask_for_go_through(
    db_client: AsyncClient, signup, create_team, add_member, agent_script
) -> None:
    ada, _, cat, ws, base = await _team(db_client, signup, create_team, add_member)
    await db_client.patch(ws, json={"approval_mode_cap": "accept_edits"}, headers=ada.headers)
    agent_script.say(tool_call("write_file", file_path="/dotrix/roadmap.md", content="# The plan"), "Written.")
    run = (await db_client.post(f"{base}/agent/runs", headers=ada.headers, json={
        "message": "Write the plan down", "approval_mode": "auto",
    })).json()
    assert run["status"] == "completed" and not run["approvals"], run
    assert run["approval_mode"] == "accept_edits"  # capped by the workspace
    note = await db_client.get(f"{base}/knowledge/files/roadmap.md", headers=ada.headers)
    assert note.status_code == 200 and "The plan" in note.json()["content"]
    [event] = [e for e in (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()
               if e["action"] == "knowledge.write.accepted"]
    assert event["approved_by_id"] == ada.id and event["details"]["rule"]["mode"] == "accept_edits"

    # Closing an issue always needs a person, whatever the mode: here it's refused, with how to.
    issue = (await db_client.post(f"{base}/issues", headers=ada.headers, json={"type": "task", "title": "T"})).json()
    model = agent_script.say(tool_call("update_issue", key=issue["key"], status="done"), "Close it on the board.")
    await db_client.post(f"{base}/agent/runs", headers=ada.headers, json={
        "message": "Close it", "approval_mode": "accept_edits",
    })
    said = [m.content for m in model.received[-1] if m.type == "tool"][-1]
    assert "Closing an issue needs a person" in said
    assert (await db_client.get(f"{base}/issues/{issue['key']}", headers=ada.headers)).json()["status"] != "done"

    # Someone who may not approve agent changes stays on Manual: their change waits.
    agent_script.say(tool_call("create_issue", type="task", title="From Cat"), "Waiting for approval.")
    theirs = (await db_client.post(f"{base}/agent/runs", headers=cat.headers, json={
        "message": "Create it", "approval_mode": "accept_edits",
    })).json()
    assert theirs["approval_mode"] == "manual" and theirs["status"] == "awaiting_approval"


async def test_manual_is_the_default_and_a_pause_wins(
    db_client: AsyncClient, signup, create_team, add_member, agent_script
) -> None:
    ada, _, _, ws, base = await _team(db_client, signup, create_team, add_member)
    await db_client.patch(ws, json={"approval_mode_cap": "auto"}, headers=ada.headers)
    agent_script.say(tool_call("create_issue", type="task", title="A"), "Waiting.")
    plain = (await db_client.post(f"{base}/agent/runs", headers=ada.headers, json={"message": "Create it"})).json()
    assert plain["approval_mode"] == "manual" and plain["status"] == "awaiting_approval"

    await db_client.patch(ws, json={"unattended_paused": True}, headers=ada.headers)
    agent_script.say(tool_call("create_issue", type="task", title="B"), "Waiting.")
    paused = (await db_client.post(f"{base}/agent/runs", headers=ada.headers, json={
        "message": "Create it", "approval_mode": "auto",
    })).json()
    assert paused["approval_mode"] == "manual" and paused["status"] == "awaiting_approval"
