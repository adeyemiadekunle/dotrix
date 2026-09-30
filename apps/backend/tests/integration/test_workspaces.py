import uuid

from httpx import AsyncClient

from pmagent_backend.modules.workspaces.models import Role


async def test_create_and_list_workspaces(signup, create_team, db_client: AsyncClient) -> None:
    ada = await signup()
    team = await create_team(ada.headers, "Kunemi Logistics")
    assert team["kind"] == "organization" and team["role"] == "owner"
    assert team["slug"].startswith("kunemi-logistics-")

    listed = (await db_client.get("/v1/workspaces", headers=ada.headers)).json()
    assert [w["kind"] for w in listed] == ["personal", "organization"]


async def test_cannot_create_a_second_personal_workspace(signup, db_client: AsyncClient) -> None:
    ada = await signup()
    res = await db_client.post(
        "/v1/workspaces", json={"name": "Mine", "kind": "personal"}, headers=ada.headers
    )
    assert res.status_code == 422


async def test_workspaces_are_isolated_between_users(signup, create_team, db_client: AsyncClient) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    team = await create_team(ada.headers)
    ws = f"/v1/workspaces/{team['id']}"

    # Bob can't read, list members of, rename, or change members in Ada's workspace,
    # and gets 404 rather than 403 so workspace IDs can't be probed.
    assert (await db_client.get(ws, headers=bob.headers)).status_code == 404
    assert (await db_client.get(f"{ws}/members", headers=bob.headers)).status_code == 404
    assert (await db_client.patch(ws, json={"name": "x"}, headers=bob.headers)).status_code == 404
    res = await db_client.patch(
        f"{ws}/members/{ada.id}", json={"role": "guest"}, headers=bob.headers
    )
    assert res.status_code == 404
    assert (await db_client.delete(f"{ws}/members/{ada.id}", headers=bob.headers)).status_code == 404
    # And it never appears in his list.
    bobs = (await db_client.get("/v1/workspaces", headers=bob.headers)).json()
    assert team["id"] not in {w["id"] for w in bobs}


async def test_unknown_workspace_is_404(signup, db_client: AsyncClient) -> None:
    ada = await signup()
    res = await db_client.get(f"/v1/workspaces/{uuid.uuid4()}", headers=ada.headers)
    assert res.status_code == 404


async def test_members_see_workspace_and_member_list(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    team = await create_team(ada.headers)
    await add_member(team["id"], bob.id, Role.MEMBER)

    got = (await db_client.get(f"/v1/workspaces/{team['id']}", headers=bob.headers)).json()
    assert got["role"] == "member"
    members = (await db_client.get(f"/v1/workspaces/{team['id']}/members", headers=bob.headers)).json()
    assert {(m["email"], m["role"]) for m in members} == {
        ("ada@example.com", "owner"),
        ("bob@example.com", "member"),
    }


async def test_rename_requires_admin(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    team = await create_team(ada.headers)
    await add_member(team["id"], bob.id, Role.MEMBER)
    ws = f"/v1/workspaces/{team['id']}"

    denied = await db_client.patch(ws, json={"name": "Renamed"}, headers=bob.headers)
    assert denied.status_code == 403
    ok = await db_client.patch(ws, json={"name": "Renamed"}, headers=ada.headers)
    assert ok.status_code == 200 and ok.json()["name"] == "Renamed"


async def test_role_changes(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    cy = await signup(email="cy@example.com", name="Cy")
    team = await create_team(ada.headers)
    ws = f"/v1/workspaces/{team['id']}"
    await add_member(team["id"], bob.id, Role.ADMIN)
    await add_member(team["id"], cy.id, Role.MEMBER)

    # Members can't change roles.
    res = await db_client.patch(f"{ws}/members/{bob.id}", json={"role": "guest"}, headers=cy.headers)
    assert res.status_code == 403
    # Admins can change non-owner roles...
    res = await db_client.patch(f"{ws}/members/{cy.id}", json={"role": "guest"}, headers=bob.headers)
    assert res.status_code == 200 and res.json()["role"] == "guest"
    # ...but can't grant owner or touch an owner.
    res = await db_client.patch(f"{ws}/members/{cy.id}", json={"role": "owner"}, headers=bob.headers)
    assert res.status_code == 403
    res = await db_client.patch(f"{ws}/members/{ada.id}", json={"role": "member"}, headers=bob.headers)
    assert res.status_code == 403


async def test_workspace_always_keeps_an_owner(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    team = await create_team(ada.headers)
    ws = f"/v1/workspaces/{team['id']}"
    await add_member(team["id"], bob.id, Role.MEMBER)

    # The only owner can't step down or leave.
    res = await db_client.patch(f"{ws}/members/{ada.id}", json={"role": "admin"}, headers=ada.headers)
    assert res.status_code == 409
    assert (await db_client.delete(f"{ws}/members/{ada.id}", headers=ada.headers)).status_code == 409

    # After promoting Bob, Ada can step down.
    res = await db_client.patch(f"{ws}/members/{bob.id}", json={"role": "owner"}, headers=ada.headers)
    assert res.status_code == 200
    res = await db_client.patch(f"{ws}/members/{ada.id}", json={"role": "admin"}, headers=ada.headers)
    assert res.status_code == 200 and res.json()["role"] == "admin"


async def test_remove_and_leave(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    cy = await signup(email="cy@example.com", name="Cy")
    team = await create_team(ada.headers)
    ws = f"/v1/workspaces/{team['id']}"
    await add_member(team["id"], bob.id, Role.MEMBER)
    await add_member(team["id"], cy.id, Role.MEMBER)

    # A member can't remove someone else, but can leave.
    assert (await db_client.delete(f"{ws}/members/{cy.id}", headers=bob.headers)).status_code == 403
    assert (await db_client.delete(f"{ws}/members/{bob.id}", headers=bob.headers)).status_code == 204
    assert (await db_client.get(ws, headers=bob.headers)).status_code == 404
    # The owner can remove members.
    assert (await db_client.delete(f"{ws}/members/{cy.id}", headers=ada.headers)).status_code == 204
    members = (await db_client.get(f"{ws}/members", headers=ada.headers)).json()
    assert [m["email"] for m in members] == ["ada@example.com"]


async def test_turn_a_personal_workspace_into_an_organisation(signup, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    personal = (await db_client.get("/v1/workspaces", headers=ada.headers)).json()[0]
    ws = f"/v1/workspaces/{personal['id']}"
    project = await db_client.post(f"{ws}/projects", json={"key": "KUN", "name": "Kunemi"}, headers=ada.headers)
    assert project.status_code == 201

    # Only its owner can; a guest gets 403.
    await add_member(personal["id"], bob.id, Role.GUEST)
    assert (await db_client.post(f"{ws}/convert-to-organization", json={}, headers=bob.headers)).status_code == 403

    res = await db_client.post(f"{ws}/convert-to-organization", json={"name": "Kunemi"}, headers=ada.headers)
    assert res.status_code == 200
    assert res.json()["kind"] == "organization" and res.json()["name"] == "Kunemi" and res.json()["id"] == personal["id"]
    # Its projects stay with it, and Ada gets a new, empty personal workspace.
    assert [p["key"] for p in (await db_client.get(f"{ws}/projects", headers=ada.headers)).json()] == ["KUN"]
    listed = (await db_client.get("/v1/workspaces", headers=ada.headers)).json()
    assert [w["kind"] for w in listed] == ["organization", "personal"]
    fresh = listed[1]
    assert (await db_client.get(f"/v1/workspaces/{fresh['id']}/projects", headers=ada.headers)).json() == []

    # Already an organisation.
    again = await db_client.post(f"{ws}/convert-to-organization", json={}, headers=ada.headers)
    assert again.status_code == 409
