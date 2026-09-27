from httpx import AsyncClient

from pmagent_backend.modules.workspaces.models import Role


def projects_url(team: dict) -> str:
    return f"/v1/workspaces/{team['id']}/projects"


async def test_create_project_scaffolds_pmagent(signup, create_team, db_client: AsyncClient) -> None:
    ada = await signup()
    team = await create_team(ada.headers)
    res = await db_client.post(
        projects_url(team),
        json={"key": "kun", "name": "Kunemi", "description": "Logistics", "source": "existing_repo",
              "repo_url": "https://github.com/example/kunemi", "readme": "# Kunemi\nDeliveries."},
        headers=ada.headers,
    )
    assert res.status_code == 201, res.text
    project = res.json()
    assert project["key"] == "KUN"  # normalised to upper case
    assert project["knowledge_revision"] == 1
    assert project["repo_url"] == "https://github.com/example/kunemi"

    manifest = (
        await db_client.get(f"{projects_url(team)}/{project['id']}/knowledge", headers=ada.headers)
    ).json()
    paths = {f["path"] for f in manifest["files"]}
    assert {"project.md", "requirements/product.md", "decisions/README.md", "agent-rules/base.md"} <= paths
    assert all(f["version"] == 1 and f["revision"] == 1 for f in manifest["files"])

    project_md = (
        await db_client.get(
            f"{projects_url(team)}/{project['id']}/knowledge/files/project.md", headers=ada.headers
        )
    ).json()
    assert project_md["content"].startswith("# Kunemi\n\nLogistics")
    assert "Deliveries." in project_md["content"]


async def test_project_keys_are_unique_per_workspace(signup, create_team, db_client: AsyncClient) -> None:
    ada = await signup()
    team = await create_team(ada.headers)
    other = await create_team(ada.headers, "Other")
    body = {"key": "KUN", "name": "Kunemi"}
    assert (await db_client.post(projects_url(team), json=body, headers=ada.headers)).status_code == 201
    dup = await db_client.post(projects_url(team), json=body | {"key": "kun"}, headers=ada.headers)
    assert dup.status_code == 409 and dup.json()["type"].endswith("/key_taken")
    # Same key in another workspace is fine.
    assert (await db_client.post(projects_url(other), json=body, headers=ada.headers)).status_code == 201


async def test_invalid_keys(signup, create_team, db_client: AsyncClient) -> None:
    ada = await signup()
    team = await create_team(ada.headers)
    for key in ("K", "1KUN", "KU-N", "TOOLONGKEY1"):
        res = await db_client.post(projects_url(team), json={"key": key, "name": "x"}, headers=ada.headers)
        assert res.status_code == 422, key


async def test_list_get_and_update(signup, create_team, db_client: AsyncClient) -> None:
    ada = await signup()
    team = await create_team(ada.headers)
    for key in ("ZED", "ABC"):
        await db_client.post(projects_url(team), json={"key": key, "name": key}, headers=ada.headers)
    listed = (await db_client.get(projects_url(team), headers=ada.headers)).json()
    assert [p["key"] for p in listed] == ["ABC", "ZED"]

    url = f"{projects_url(team)}/{listed[0]['id']}"
    res = await db_client.patch(url, json={"name": "Renamed"}, headers=ada.headers)
    assert res.status_code == 200 and res.json()["name"] == "Renamed" and res.json()["key"] == "ABC"
    assert (await db_client.get(url, headers=ada.headers)).json()["name"] == "Renamed"


async def test_project_permissions(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    guest = await signup(email="guest@example.com", name="Guest")
    eve = await signup(email="eve@example.com", name="Eve")
    team = await create_team(ada.headers)
    await add_member(team["id"], bob.id, Role.MEMBER)
    await add_member(team["id"], guest.id, Role.GUEST)
    project = (
        await db_client.post(projects_url(team), json={"key": "KUN", "name": "K"}, headers=ada.headers)
    ).json()
    url = f"{projects_url(team)}/{project['id']}"

    # Members see projects but don't set them up (owners and admins do).
    assert (await db_client.get(url, headers=bob.headers)).status_code == 200
    res = await db_client.post(projects_url(team), json={"key": "BOB", "name": "B"}, headers=bob.headers)
    assert res.status_code == 403
    # Guests see no projects until project-level invites exist, and can't create any.
    assert (await db_client.get(projects_url(team), headers=guest.headers)).json() == []
    assert (await db_client.get(url, headers=guest.headers)).status_code == 404
    res = await db_client.post(projects_url(team), json={"key": "GST", "name": "G"}, headers=guest.headers)
    assert res.status_code == 403
    # Outsiders can't tell the workspace or project exists.
    assert (await db_client.get(url, headers=eve.headers)).status_code == 404
    assert (await db_client.get(projects_url(team), headers=eve.headers)).status_code == 404


async def test_project_from_another_workspace_is_404(signup, create_team, db_client: AsyncClient) -> None:
    ada = await signup()
    team = await create_team(ada.headers)
    other = await create_team(ada.headers, "Other")
    project = (
        await db_client.post(projects_url(team), json={"key": "KUN", "name": "K"}, headers=ada.headers)
    ).json()
    # Right project ID, wrong workspace in the URL.
    res = await db_client.get(f"{projects_url(other)}/{project['id']}", headers=ada.headers)
    assert res.status_code == 404


async def test_project_model_choice(signup, create_team, db_client: AsyncClient) -> None:
    ada = await signup()
    team = await create_team(ada.headers)
    default = (await db_client.post(projects_url(team), json={"key": "DEF", "name": "D"}, headers=ada.headers)).json()
    assert default["model"] == "anthropic:claude-sonnet-5"  # the server default
    chosen = await db_client.post(
        projects_url(team), json={"key": "GEM", "name": "G", "model": "google_genai:gemini-3.8-flash"},
        headers=ada.headers,
    )
    assert chosen.json()["model"] == "google_genai:gemini-3.8-flash"
    url = f"{projects_url(team)}/{default['id']}"
    changed = await db_client.patch(url, json={"model": "openai:gpt-5"}, headers=ada.headers)
    assert changed.json()["model"] == "openai:gpt-5"
    for bad in ("gpt-5", "mistral:large", "anthropic:"):
        res = await db_client.patch(url, json={"model": bad}, headers=ada.headers)
        assert res.status_code == 422, bad


async def test_repo_urls_are_canonical_and_matchable(signup, create_team, db_client: AsyncClient) -> None:
    ada = await signup()
    team = await create_team(ada.headers)
    res = await db_client.post(
        projects_url(team),
        json={"key": "KUN", "name": "K", "repo_url": "https://ada:ghp_secret@GitHub.com/acme/kunemi.git"},
        headers=ada.headers,
    )
    assert res.status_code == 201
    assert res.json()["repo_url"] == "https://github.com/acme/kunemi"  # credentials never stored
    for form in ("git@github.com:acme/kunemi.git", "ssh://git@github.com/acme/kunemi", "https://github.com/acme/kunemi/"):
        found = (await db_client.get(projects_url(team), params={"repo_url": form}, headers=ada.headers)).json()
        assert [p["key"] for p in found] == ["KUN"], form
    other = (await db_client.get(projects_url(team), params={"repo_url": "git@github.com:acme/other"}, headers=ada.headers)).json()
    assert other == []
    dup = await db_client.post(
        projects_url(team), json={"key": "DUP", "name": "D", "repo_url": "git@github.com:acme/kunemi.git"},
        headers=ada.headers,
    )
    assert dup.status_code == 409 and dup.json()["type"].endswith("/repo_taken")
    bad = await db_client.get(projects_url(team), params={"repo_url": "not a url"}, headers=ada.headers)
    assert bad.status_code == 422


async def test_admins_set_up_projects(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    cy = await signup(email="cy@example.com", name="Cy")
    team = await create_team(ada.headers)
    await add_member(team["id"], cy.id, Role.ADMIN)
    res = await db_client.post(projects_url(team), json={"key": "ADM", "name": "A"}, headers=cy.headers)
    assert res.status_code == 201
