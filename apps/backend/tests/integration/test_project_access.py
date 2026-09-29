"""Project access: a project is open to every member of its workspace, or restricted to its
owners, admins, and the people added to it (docs/agents-v2.md §0)."""
from httpx import AsyncClient

from pmagent_backend.modules.workspaces.models import Role
from pmagent_engine.testing import tool_call


async def _setup(signup, create_team, add_member, db_client: AsyncClient):
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    cat = await signup(email="cat@example.com", name="Cat")
    team = await create_team(ada.headers)
    await add_member(team["id"], bob.id, Role.MEMBER)
    await add_member(team["id"], cat.id, Role.ADMIN)
    ws = f"/v1/workspaces/{team['id']}"
    project = (await db_client.post(f"{ws}/projects", json={"key": "KUN", "name": "Kunemi"}, headers=ada.headers)).json()
    return ada, bob, cat, ws, f"{ws}/projects/{project['id']}"


async def test_restricting_a_project_hides_it_from_members_not_added(
    signup, create_team, add_member, db_client: AsyncClient
) -> None:
    ada, bob, cat, ws, base = await _setup(signup, create_team, add_member, db_client)
    assert (await db_client.get(base, headers=bob.headers)).json()["access"] == "workspace"
    people = (await db_client.get(f"{base}/members", headers=bob.headers)).json()
    assert {(p["email"], p["via"]) for p in people} == {
        ("ada@example.com", "role"), ("bob@example.com", "workspace"), ("cat@example.com", "role")
    }

    # Bob is assigned an issue and watches it; restricting the project takes both away.
    issue = await db_client.post(
        f"{base}/issues", json={"type": "task", "title": "x", "assignee_user_id": bob.id}, headers=ada.headers
    )
    assert issue.status_code == 201
    assert (await db_client.put(f"{base}/issues/KUN-1/watch", headers=bob.headers)).status_code == 200

    # Members can't change who sees it.
    assert (await db_client.patch(base, json={"access": "restricted"}, headers=bob.headers)).status_code == 403
    res = await db_client.patch(base, json={"access": "restricted"}, headers=ada.headers)
    assert res.status_code == 200 and res.json()["access"] == "restricted"

    assert (await db_client.get(base, headers=bob.headers)).status_code == 404
    assert (await db_client.get(f"{ws}/projects", headers=bob.headers)).json() == []
    assert (await db_client.get(base, headers=cat.headers)).status_code == 200  # admins always see it
    got = (await db_client.get(f"{base}/issues/KUN-1", headers=ada.headers)).json()
    assert got["assignee_user_id"] is None and bob.id not in got["watchers"]
    # Nobody can assign it to someone who can't see it.
    denied = await db_client.patch(f"{base}/issues/KUN-1", json={"assignee_user_id": bob.id}, headers=ada.headers)
    assert denied.status_code == 422

    # Added, Bob sees it again; removed, he doesn't.
    added = await db_client.put(f"{base}/members/{bob.id}", headers=cat.headers)
    assert added.status_code == 200
    assert ("bob@example.com", "added") in {(p["email"], p["via"]) for p in added.json()}
    assert (await db_client.get(base, headers=bob.headers)).status_code == 200
    assert (await db_client.patch(f"{base}/issues/KUN-1", json={"assignee_user_id": bob.id}, headers=ada.headers)).status_code == 200
    assert (await db_client.delete(f"{base}/members/{bob.id}", headers=ada.headers)).status_code == 204
    assert (await db_client.get(base, headers=bob.headers)).status_code == 404
    assert (await db_client.get(f"{base}/issues/KUN-1", headers=ada.headers)).json()["assignee_user_id"] is None
    assert (await db_client.delete(f"{base}/members/{bob.id}", headers=ada.headers)).status_code == 404

    audit = (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()
    actions = [e["action"] for e in audit]
    assert {"project.access_changed", "project.member_added", "project.member_removed"} <= set(actions)


async def test_guests_and_strangers_cant_be_added(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada, _, _, ws, base = await _setup(signup, create_team, add_member, db_client)
    guest = await signup(email="gus@example.com", name="Gus")
    stranger = await signup(email="sam@example.com", name="Sam")
    await add_member(ws.rsplit("/", 1)[1], guest.id, Role.GUEST)
    assert (await db_client.put(f"{base}/members/{guest.id}", headers=ada.headers)).status_code == 409
    assert (await db_client.put(f"{base}/members/{stranger.id}", headers=ada.headers)).status_code == 404


async def test_create_a_restricted_project(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    team = await create_team(ada.headers)
    await add_member(team["id"], bob.id, Role.MEMBER)
    ws = f"/v1/workspaces/{team['id']}"
    res = await db_client.post(
        f"{ws}/projects", json={"key": "SEC", "name": "Secret", "access": "restricted"}, headers=ada.headers
    )
    assert res.status_code == 201 and res.json()["access"] == "restricted"
    assert (await db_client.get(f"{ws}/projects", headers=bob.headers)).json() == []


async def test_the_approvals_queue_leaves_out_projects_you_cant_see(
    signup, create_team, add_member, db_client: AsyncClient, agent_script
) -> None:
    ada, bob, _, ws, base = await _setup(signup, create_team, add_member, db_client)
    agent_script.say(tool_call("write_file", file_path="/pmagent/roadmap.md", content="# R\n"), "Done.")
    run = (await db_client.post(f"{base}/agent/runs", json={"message": "Plan"}, headers=ada.headers)).json()
    assert run["status"] == "awaiting_approval"
    assert len((await db_client.get(f"{ws}/approvals", headers=bob.headers)).json()) == 1
    await db_client.patch(base, json={"access": "restricted"}, headers=ada.headers)
    assert (await db_client.get(f"{ws}/approvals", headers=bob.headers)).json() == []
    assert len((await db_client.get(f"{ws}/approvals", headers=ada.headers)).json()) == 1
