from httpx import AsyncClient

from pmagent_backend.modules.workspaces.models import Role


async def test_teams_hold_people_and_projects_one_each(db_client: AsyncClient, signup, create_team, add_member) -> None:
    ada = await signup()
    ws = await create_team(ada.headers)
    url = f"/v1/workspaces/{ws['id']}/teams"
    grace = await signup(email="grace@example.com", name="Grace")
    await add_member(ws["id"], grace.id, Role.MEMBER)
    project = (await db_client.post(f"/v1/workspaces/{ws['id']}/projects", json={"key": "WEB", "name": "Web"},
                                    headers=ada.headers)).json()

    design = await db_client.post(url, json={"name": "Design", "icon": "palette", "color": "#8662C9"}, headers=ada.headers)
    assert design.status_code == 201, design.text
    eng = (await db_client.post(url, json={"name": "Engineering"}, headers=ada.headers)).json()
    taken = await db_client.post(url, json={"name": "Design"}, headers=ada.headers)
    assert taken.status_code == 409
    bad = await db_client.post(url, json={"name": "Ops", "color": "red"}, headers=ada.headers)
    assert bad.status_code == 422

    team = design.json()
    joined = await db_client.put(f"{url}/{team['id']}/members/{grace.id}", headers=ada.headers)
    assert joined.status_code == 200 and joined.json()["member_ids"] == [grace.id]
    # One team each: joining Engineering takes Grace out of Design.
    await db_client.put(f"{url}/{eng['id']}/members/{grace.id}", headers=ada.headers)
    await db_client.put(f"{url}/{team['id']}/projects/{project['id']}", headers=ada.headers)
    await db_client.put(f"{url}/{eng['id']}/projects/{project['id']}", headers=ada.headers)
    listed = {t["name"]: t for t in (await db_client.get(url, headers=grace.headers)).json()}
    assert list(listed) == ["Design", "Engineering"]  # by name, for every member
    assert listed["Design"]["member_ids"] == [] and listed["Design"]["project_ids"] == []
    assert listed["Engineering"]["member_ids"] == [grace.id]
    assert listed["Engineering"]["project_ids"] == [project["id"]]

    renamed = await db_client.patch(f"{url}/{team['id']}", json={"name": "Product design", "description": "UX"},
                                    headers=ada.headers)
    assert renamed.status_code == 200
    assert (renamed.json()["name"], renamed.json()["description"], renamed.json()["icon"]) == ("Product design", "UX", "palette")

    left = await db_client.delete(f"{url}/{eng['id']}/members/{grace.id}", headers=ada.headers)
    assert left.json()["member_ids"] == []
    assert (await db_client.delete(f"{url}/{eng['id']}", headers=ada.headers)).status_code == 204
    assert [t["name"] for t in (await db_client.get(url, headers=ada.headers)).json()] == ["Product design"]
    # The project and its people stay.
    assert (await db_client.get(f"/v1/workspaces/{ws['id']}/projects/{project['id']}", headers=ada.headers)).status_code == 200

    audit = (await db_client.get(f"/v1/workspaces/{ws['id']}/audit", headers=ada.headers)).json()
    assert {"team.created", "team.member_added", "team.project_added", "team.deleted"} <= {a["action"] for a in audit}


async def test_members_see_teams_but_only_owners_and_admins_change_them(
    db_client: AsyncClient, signup, create_team, add_member
) -> None:
    ada = await signup()
    ws = await create_team(ada.headers)
    url = f"/v1/workspaces/{ws['id']}/teams"
    grace = await signup(email="grace@example.com", name="Grace")
    await add_member(ws["id"], grace.id, Role.MEMBER)
    team = (await db_client.post(url, json={"name": "Design"}, headers=ada.headers)).json()

    assert (await db_client.get(url, headers=grace.headers)).status_code == 200
    assert (await db_client.post(url, json={"name": "Mine"}, headers=grace.headers)).status_code == 403
    assert (await db_client.put(f"{url}/{team['id']}/members/{grace.id}", headers=grace.headers)).status_code == 403
    assert (await db_client.delete(f"{url}/{team['id']}", headers=grace.headers)).status_code == 403
    # Someone outside the workspace can't be put in a team.
    stranger = await signup(email="stranger@example.com", name="Stranger")
    assert (await db_client.put(f"{url}/{team['id']}/members/{stranger.id}", headers=ada.headers)).status_code == 404


async def test_a_restricted_project_shows_under_its_team_only_to_who_sees_it(
    db_client: AsyncClient, signup, create_team, add_member
) -> None:
    ada = await signup()
    ws = await create_team(ada.headers)
    url = f"/v1/workspaces/{ws['id']}/teams"
    grace = await signup(email="grace@example.com", name="Grace")
    await add_member(ws["id"], grace.id, Role.MEMBER)
    secret = (await db_client.post(f"/v1/workspaces/{ws['id']}/projects",
                                   json={"key": "SEC", "name": "Secret", "access": "restricted"}, headers=ada.headers)).json()
    team = (await db_client.post(url, json={"name": "Security"}, headers=ada.headers)).json()
    await db_client.put(f"{url}/{team['id']}/projects/{secret['id']}", headers=ada.headers)

    assert (await db_client.get(url, headers=ada.headers)).json()[0]["project_ids"] == [secret["id"]]
    assert (await db_client.get(url, headers=grace.headers)).json()[0]["project_ids"] == []
