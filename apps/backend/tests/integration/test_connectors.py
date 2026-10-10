"""Connecting GitHub through the app: installations proven by a GitHub sign-in, each project's
repo, and the webhook keeping them current. GitHub is faked (conftest.FakeGitHub)."""
from httpx import AsyncClient


async def test_not_set_up(db_client: AsyncClient, github_world) -> None:
    ada, _, ws, _, _ = await github_world()
    assert (await db_client.get(f"{ws}/github", headers=ada.headers)).json() == {
        "configured": False, "install_url": None, "installations": []
    }


async def test_install_then_connect_a_repo(db_client: AsyncClient, github_world, github) -> None:
    ada, cat, ws, kun, mob = await github_world()
    status = (await db_client.get(f"{ws}/github", headers=ada.headers)).json()
    assert status["configured"] and status["install_url"] == "https://github.com/apps/dotrix-test/installations/new"
    # Members don't set up projects' code.
    assert (await db_client.get(f"{ws}/github", headers=cat.headers)).status_code == 403

    # Only an installation GitHub says you manage.
    theirs = await db_client.post(f"{ws}/github/installations", json={"installation_id": 222, "code": "code-1"},
                                  headers=ada.headers)
    assert theirs.status_code == 403
    added = await db_client.post(f"{ws}/github/installations", json={"installation_id": 111, "code": "code-2"},
                                 headers=ada.headers)
    assert added.status_code == 200, added.text
    installation = added.json()
    assert installation["account_login"] == "kunemi" and installation["account_type"] == "Organization"

    repos = (await db_client.get(f"{ws}/github/repos", headers=ada.headers)).json()
    assert [(r["full_name"], r["private"], r["project_key"]) for r in repos] == [
        ("kunemi/api", True, None), ("kunemi/web", False, None)
    ]

    base = f"{ws}/projects/{kun['id']}/repository"
    connect = {"installation_ref": installation["id"], "github_repo_id": 9001}
    res = await db_client.put(base, json=connect, headers=ada.headers)
    assert res.status_code == 200, res.text
    assert res.json()["full_name"] == "kunemi/api" and res.json()["account_login"] == "kunemi"
    project = (await db_client.get(f"{ws}/projects/{kun['id']}", headers=ada.headers)).json()
    assert project["repo_url"] == "https://github.com/kunemi/api"
    # Anyone who sees the project sees its repo; another project can't take it.
    assert (await db_client.get(base, headers=cat.headers)).json()["full_name"] == "kunemi/api"
    taken = await db_client.put(f"{ws}/projects/{mob['id']}/repository", json=connect, headers=ada.headers)
    assert taken.status_code == 409 and "KUN already uses kunemi/api" in taken.json()["detail"]
    # A repo the installation can't see isn't there.
    hidden = await db_client.put(f"{ws}/projects/{mob['id']}/repository",
                                 json={**connect, "github_repo_id": 9100}, headers=ada.headers)
    assert hidden.status_code == 404
    assert [r["project_key"] for r in (await db_client.get(f"{ws}/github/repos", headers=ada.headers)).json()] == [
        "KUN", None
    ]

    # Disconnecting keeps the repo's address (for the CLI).
    assert (await db_client.delete(base, headers=ada.headers)).status_code == 204
    assert (await db_client.get(base, headers=ada.headers)).json() is None
    assert (await db_client.delete(base, headers=ada.headers)).status_code == 404


async def test_the_webhook_keeps_it_current(db_client: AsyncClient, github_world, deliver, github) -> None:
    ada, _, ws, kun, mob = await github_world()
    installation = (await db_client.post(f"{ws}/github/installations", json={"installation_id": 111, "code": "code-1"},
                                          headers=ada.headers)).json()
    for project, repo_id in ((kun, 9001), (mob, 9002)):
        await db_client.put(f"{ws}/projects/{project['id']}/repository",
                            json={"installation_ref": installation["id"], "github_repo_id": repo_id}, headers=ada.headers)

    push = {"ref": "refs/heads/main", "after": "a" * 40,
            "repository": {"id": 9001, "full_name": "kunemi/api-renamed", "default_branch": "main"}}
    assert (await deliver("push", push, secret="wrong")).status_code == 401
    assert (await deliver("push", push)).status_code == 202
    repo = (await db_client.get(f"{ws}/projects/{kun['id']}/repository", headers=ada.headers)).json()
    assert repo["last_push_sha"] == "a" * 40 and repo["full_name"] == "kunemi/api-renamed"
    # Pushes to other branches don't count.
    await deliver("push", {**push, "ref": "refs/heads/feature", "after": "b" * 40})
    assert (await db_client.get(f"{ws}/projects/{kun['id']}/repository", headers=ada.headers)).json()["last_push_sha"] == "a" * 40

    # A repo taken away from the app: its project is disconnected.
    removed = {"action": "removed", "installation": {"id": 111}, "repositories_removed": [{"id": 9002}]}
    await deliver("installation_repositories", removed)
    assert (await db_client.get(f"{ws}/projects/{mob['id']}/repository", headers=ada.headers)).json() is None
    # Uninstalled: forgotten, and its projects disconnected.
    await deliver("installation", {"action": "deleted", "installation": {"id": 111}})
    assert (await db_client.get(f"{ws}/github", headers=ada.headers)).json()["installations"] == []
    assert (await db_client.get(f"{ws}/projects/{kun['id']}/repository", headers=ada.headers)).json() is None


async def test_forget_an_installation(db_client: AsyncClient, github_world, github) -> None:
    ada, _, ws, kun, _ = await github_world()
    installation = (await db_client.post(f"{ws}/github/installations", json={"installation_id": 111, "code": "code-1"},
                                          headers=ada.headers)).json()
    await db_client.put(f"{ws}/projects/{kun['id']}/repository",
                        json={"installation_ref": installation["id"], "github_repo_id": 9001}, headers=ada.headers)
    gone = await db_client.delete(f"{ws}/github/installations/{installation['id']}", headers=ada.headers)
    assert gone.status_code == 204
    assert (await db_client.get(f"{ws}/projects/{kun['id']}/repository", headers=ada.headers)).json() is None
    audit = (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()
    actions = {e["action"] for e in (audit["items"] if isinstance(audit, dict) else audit)}
    assert {"github.installation_added", "project.repo_connected", "github.installation_removed"} <= actions


async def test_moving_a_project_drops_its_connection(db_client: AsyncClient, github_world, create_team, github) -> None:
    ada, _, ws, kun, _ = await github_world()
    installation = (await db_client.post(f"{ws}/github/installations", json={"installation_id": 111, "code": "code-1"},
                                          headers=ada.headers)).json()
    await db_client.put(f"{ws}/projects/{kun['id']}/repository",
                        json={"installation_ref": installation["id"], "github_repo_id": 9001}, headers=ada.headers)
    other = await create_team(ada.headers, "Other")
    moved = await db_client.post(f"{ws}/projects/{kun['id']}/move", json={"workspace_id": other["id"]}, headers=ada.headers)
    assert moved.status_code == 200, moved.text
    # The installation belongs to the old workspace: the project keeps its address, not the connection.
    there = f"/v1/workspaces/{other['id']}/projects/{kun['id']}"
    assert (await db_client.get(f"{there}/repository", headers=ada.headers)).json() is None
    assert (await db_client.get(there, headers=ada.headers)).json()["repo_url"] == "https://github.com/kunemi/api"
    assert [r["project_key"] for r in (await db_client.get(f"{ws}/github/repos", headers=ada.headers)).json()] == [None, None]


async def test_create_a_repo_in_an_organisation(db_client: AsyncClient, github_world, github) -> None:
    ada, cat, ws, kun, _ = await github_world()
    org = (await db_client.post(f"{ws}/github/installations", json={"installation_id": 111, "code": "code-1"},
                                 headers=ada.headers)).json()
    personal = (await db_client.post(f"{ws}/github/installations", json={"installation_id": 333, "code": "code-2"},
                                      headers=ada.headers)).json()
    body = {"installation_ref": org["id"], "name": "kun-app", "private": True, "description": "Kunemi"}
    assert (await db_client.post(f"{ws}/github/repos", json=body, headers=cat.headers)).status_code == 403
    res = await db_client.post(f"{ws}/github/repos", json=body, headers=ada.headers)
    assert res.status_code == 201, res.text
    repo = res.json()
    assert (repo["full_name"], repo["private"], repo["project_key"]) == ("kunemi/kun-app", True, None)
    # Ready to connect like any other.
    connect = {"installation_ref": org["id"], "github_repo_id": repo["github_repo_id"]}
    assert (await db_client.put(f"{ws}/projects/{kun['id']}/repository", json=connect, headers=ada.headers)).status_code == 200

    assert (await db_client.post(f"{ws}/github/repos", json=body, headers=ada.headers)).status_code == 409
    # GitHub doesn't let apps create repos in a person's own account.
    mine = await db_client.post(f"{ws}/github/repos", json={**body, "installation_ref": personal["id"]}, headers=ada.headers)
    assert mine.status_code == 403 and "only in organisations" in mine.json()["detail"]
    assert (await db_client.post(f"{ws}/github/repos", json={**body, "name": "bad name!"}, headers=ada.headers)).status_code == 422
    audit = (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()
    assert "github.repo_created" in {e["action"] for e in (audit["items"] if isinstance(audit, dict) else audit)}
