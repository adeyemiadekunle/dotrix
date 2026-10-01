"""A project's activity feed: issues, documents, runs, and decisions, newest first."""
from httpx import AsyncClient

from pmagent_backend.modules.workspaces.models import Role


async def test_project_activity(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    guest = await signup(email="gus@example.com", name="Gus")
    team = await create_team(ada.headers)
    await add_member(team["id"], guest.id, Role.GUEST)
    ws = f"/v1/workspaces/{team['id']}"
    project = (
        await db_client.post(f"{ws}/projects", json={"key": "KUN", "name": "Kunemi"}, headers=ada.headers)
    ).json()
    base = f"{ws}/projects/{project['id']}"

    # A new project's skeleton isn't anyone's act: nothing to show yet.
    assert (await db_client.get(f"{base}/activity", headers=ada.headers)).json() == []

    issue = (await db_client.post(f"{base}/issues", json={"title": "Guest checkout"}, headers=ada.headers)).json()
    await db_client.patch(f"{base}/issues/{issue['key']}", json={"priority": "high"}, headers=ada.headers)
    await db_client.post(f"{base}/issues/{issue['key']}/comments", json={"body": "Needs legal"}, headers=ada.headers)
    res = await db_client.put(
        f"{base}/knowledge/files/requirements/product.md",
        json={"content": "# Product\n", "base_version": 1, "message": "Scope it"},
        headers=ada.headers,
    )
    assert res.status_code == 200, res.text

    feed = (await db_client.get(f"{base}/activity", headers=ada.headers)).json()
    assert [item["kind"] for item in feed] == [
        "document.changed",
        "issue.commented",
        "issue.updated",
        "issue.created",
    ]
    document, comment, update, created = feed
    assert document["path"] == "requirements/product.md" and document["version"] == 2
    assert document["body"] == "Scope it" and document["actor_user_id"] == ada.id
    assert comment["body"] == "Needs legal" and comment["issue_key"] == issue["key"]
    assert update["changes"]["priority"] == ["medium", "high"]
    assert created["issue_title"] == "Guest checkout"

    # Paging back from the last item you have.
    older = await db_client.get(f"{base}/activity", params={"before": update["at"]}, headers=ada.headers)
    assert [item["kind"] for item in older.json()] == ["issue.created"]
    assert len((await db_client.get(f"{base}/activity", params={"limit": 2}, headers=ada.headers)).json()) == 2

    # Guests see no projects, so no activity either.
    assert (await db_client.get(f"{base}/activity", headers=guest.headers)).status_code == 404


async def test_workspace_activity(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    team = await create_team(ada.headers)
    await add_member(team["id"], bob.id, Role.MEMBER)
    ws = f"/v1/workspaces/{team['id']}"
    projects = {}
    for key in ("KUN", "MOB"):
        projects[key] = (
            await db_client.post(f"{ws}/projects", json={"key": key, "name": key.title()}, headers=ada.headers)
        ).json()
        await db_client.post(f"{ws}/projects/{projects[key]['id']}/issues", json={"title": f"{key} work"}, headers=ada.headers)

    feed = (await db_client.get(f"{ws}/activity", headers=ada.headers)).json()
    assert [(i["project_key"], i["issue_title"]) for i in feed] == [("MOB", "MOB work"), ("KUN", "KUN work")]

    await db_client.patch(f"{ws}/projects/{projects['MOB']['id']}", json={"access": "restricted"}, headers=ada.headers)
    seen = (await db_client.get(f"{ws}/activity", headers=bob.headers)).json()
    assert [i["project_key"] for i in seen] == ["KUN"]
