from httpx import AsyncClient

from dotrix_backend.modules.workspaces.models import Role


def projects_url(team: dict) -> str:
    return f"/v1/workspaces/{team['id']}/projects"


async def test_create_project_scaffolds_dotrix(signup, create_team, db_client: AsyncClient) -> None:
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


async def test_link_and_unlink_a_repo_later(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    team = await create_team(ada.headers)
    docs = (await db_client.post(projects_url(team), json={"key": "DOC", "name": "Docs first"}, headers=ada.headers)).json()
    other = (await db_client.post(
        projects_url(team), json={"key": "OTH", "name": "O", "repo_url": "https://github.com/acme/other"}, headers=ada.headers,
    )).json()
    url = f"{projects_url(team)}/{docs['id']}"

    linked = await db_client.patch(url, json={"repo_url": "git@github.com:acme/kunemi.git"}, headers=ada.headers)
    assert linked.status_code == 200
    assert linked.json()["repo_url"] == "https://github.com/acme/kunemi"
    assert linked.json()["source"] == "docs_only"  # how it started doesn't change
    renamed = await db_client.patch(url, json={"name": "Renamed"}, headers=ada.headers)
    assert renamed.json()["repo_url"] == "https://github.com/acme/kunemi"  # left out: kept

    taken = await db_client.patch(url, json={"repo_url": other["repo_url"]}, headers=ada.headers)
    assert taken.status_code == 409 and taken.json()["type"].endswith("/repo_taken")
    same = await db_client.patch(
        f"{projects_url(team)}/{other['id']}", json={"repo_url": "https://github.com/acme/other.git"}, headers=ada.headers,
    )
    assert same.status_code == 200  # re-linking its own repo isn't a conflict

    bob = await signup(email="bob@example.com", name="Bob")
    await add_member(team["id"], bob.id, Role.MEMBER)
    denied = await db_client.patch(url, json={"repo_url": None}, headers=bob.headers)
    assert denied.status_code == 403  # linking the repo is setup: owners and admins

    unlinked = await db_client.patch(url, json={"repo_url": None}, headers=ada.headers)
    assert unlinked.status_code == 200 and unlinked.json()["repo_url"] is None


async def test_admins_set_up_projects(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    cy = await signup(email="cy@example.com", name="Cy")
    team = await create_team(ada.headers)
    await add_member(team["id"], cy.id, Role.ADMIN)
    res = await db_client.post(projects_url(team), json={"key": "ADM", "name": "A"}, headers=cy.headers)
    assert res.status_code == 201


async def _personal(db_client: AsyncClient, headers: dict) -> dict:
    return next(w for w in (await db_client.get("/v1/workspaces", headers=headers)).json() if w["kind"] == "personal")


async def test_move_a_project_from_personal_into_an_organisation_and_back(
    signup, create_team, db_client: AsyncClient, agent_script
) -> None:
    ada = await signup()
    personal = await _personal(db_client, ada.headers)
    team = await create_team(ada.headers, "Acme")
    project = (await db_client.post(projects_url(personal), json={"key": "KUN", "name": "Kunemi"}, headers=ada.headers)).json()
    base = f"{projects_url(personal)}/{project['id']}"
    issue = await db_client.post(f"{base}/issues", json={"type": "task", "title": "Ship it"}, headers=ada.headers)
    assert issue.status_code == 201
    await db_client.post(f"{base}/issues/KUN-1/comments", json={"body": "Soon"}, headers=ada.headers)
    agent_script.say("Hello.")
    run = (await db_client.post(f"{base}/agent/runs", json={"message": "Hi"}, headers=ada.headers)).json()
    assert run["status"] == "completed", run

    res = await db_client.post(f"{base}/move", json={"workspace_id": team["id"]}, headers=ada.headers)
    assert res.status_code == 200, res.text
    assert res.json()["workspace_id"] == team["id"] and res.json()["key"] == "KUN"

    # Everything came with it, and nothing is left behind.
    assert (await db_client.get(base, headers=ada.headers)).status_code == 404
    assert (await db_client.get(projects_url(personal), headers=ada.headers)).json() == []
    moved = f"{projects_url(team)}/{project['id']}"
    got = (await db_client.get(f"{moved}/issues/KUN-1", headers=ada.headers)).json()
    assert got["title"] == "Ship it"
    files = (await db_client.get(f"{moved}/knowledge", headers=ada.headers)).json()["files"]
    assert any(f["path"] == "project.md" for f in files)
    assert [r["id"] for r in (await db_client.get(f"{moved}/agent/runs", headers=ada.headers)).json()] == [run["id"]]
    new_issue = await db_client.post(f"{moved}/issues", json={"type": "task", "title": "Next"}, headers=ada.headers)
    assert new_issue.json()["key"] == "KUN-2"  # numbering carries on

    for ws, action in ((personal, "project.moved_out"), (team, "project.moved_in")):
        audit = (await db_client.get(f"/v1/workspaces/{ws['id']}/audit", headers=ada.headers)).json()
        assert action in {e["action"] for e in audit}

    back = await db_client.post(f"{moved}/move", json={"workspace_id": personal["id"]}, headers=ada.headers)
    assert back.status_code == 200 and back.json()["workspace_id"] == personal["id"]


async def test_moving_needs_project_setup_rights_in_both_workspaces(
    signup, create_team, add_member, db_client: AsyncClient
) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    adas = await create_team(ada.headers, "Ada's")
    bobs = await create_team(bob.headers, "Bob's")
    project = (await db_client.post(projects_url(adas), json={"key": "KUN", "name": "K"}, headers=ada.headers)).json()
    move = f"{projects_url(adas)}/{project['id']}/move"

    # Not in the target: it looks like it doesn't exist.
    res = await db_client.post(move, json={"workspace_id": bobs["id"]}, headers=ada.headers)
    assert res.status_code == 404
    # A member there can't add projects.
    await add_member(bobs["id"], ada.id, Role.MEMBER)
    assert (await db_client.post(move, json={"workspace_id": bobs["id"]}, headers=ada.headers)).status_code == 403
    # A member of the source can't move it out.
    await add_member(adas["id"], bob.id, Role.MEMBER)
    assert (await db_client.post(move, json={"workspace_id": bobs["id"]}, headers=bob.headers)).status_code == 403
    # Already there.
    assert (await db_client.post(move, json={"workspace_id": adas["id"]}, headers=ada.headers)).status_code == 409


async def test_moving_refuses_a_taken_key_or_repo_and_active_runs(
    signup, create_team, db_client: AsyncClient, agent_script
) -> None:
    from dotrix_engine.testing import tool_call

    ada = await signup()
    one = await create_team(ada.headers, "One")
    two = await create_team(ada.headers, "Two")
    repo = "https://github.com/example/kunemi"
    project = (await db_client.post(projects_url(one), json={"key": "KUN", "name": "K", "repo_url": repo},
                                    headers=ada.headers)).json()
    move = f"{projects_url(one)}/{project['id']}/move"
    taken = await db_client.post(projects_url(two), json={"key": "KUN", "name": "Other"}, headers=ada.headers)
    res = await db_client.post(move, json={"workspace_id": two["id"]}, headers=ada.headers)
    assert res.status_code == 409 and res.json()["type"].endswith("/key_taken")

    await db_client.patch(f"{projects_url(two)}/{taken.json()['id']}", json={"repo_url": repo}, headers=ada.headers)
    three = await create_team(ada.headers, "Three")
    await db_client.post(projects_url(three), json={"key": "OTH", "name": "O", "repo_url": repo}, headers=ada.headers)
    res = await db_client.post(move, json={"workspace_id": three["id"]}, headers=ada.headers)
    assert res.status_code == 409 and res.json()["type"].endswith("/repo_taken")

    four = await create_team(ada.headers, "Four")
    agent_script.say(tool_call("write_file", file_path="/dotrix/roadmap.md", content="# R\n"), "Done.")
    run = (await db_client.post(f"{projects_url(one)}/{project['id']}/agent/runs", json={"message": "Plan"},
                                headers=ada.headers)).json()
    assert run["status"] == "awaiting_approval"
    res = await db_client.post(move, json={"workspace_id": four["id"]}, headers=ada.headers)
    assert res.status_code == 409 and "agent run" in res.json()["detail"]


async def test_moving_unassigns_and_unwatches_people_who_cant_see_it(
    signup, create_team, add_member, db_client: AsyncClient
) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    cat = await signup(email="cat@example.com", name="Cat")
    one = await create_team(ada.headers, "One")
    two = await create_team(ada.headers, "Two")
    await add_member(one["id"], bob.id, Role.MEMBER)
    await add_member(one["id"], cat.id, Role.MEMBER)
    await add_member(two["id"], cat.id, Role.MEMBER)  # Cat is in both; Bob only in One
    project = (await db_client.post(projects_url(one), json={"key": "KUN", "name": "K"}, headers=ada.headers)).json()
    base = f"{projects_url(one)}/{project['id']}/issues"
    for title, who in (("Bob's", bob.id), ("Cat's", cat.id)):
        res = await db_client.post(base, json={"type": "task", "title": title, "assignee_user_id": who}, headers=ada.headers)
        assert res.status_code == 201, res.text
    for person in (ada, bob, cat):
        assert (await db_client.put(f"{base}/KUN-1/watch", headers=person.headers)).status_code == 200

    res = await db_client.post(f"{projects_url(one)}/{project['id']}/move", json={"workspace_id": two["id"]},
                               headers=ada.headers)
    assert res.status_code == 200, res.text

    moved = f"{projects_url(two)}/{project['id']}/issues"
    bobs = (await db_client.get(f"{moved}/KUN-1", headers=ada.headers)).json()
    assert bobs["assignee_user_id"] is None
    assert set(bobs["watchers"]) == {ada.id, cat.id}
    assert bobs["log"][-1]["changes"] == {"assignee_user_id": [bob.id, None]}
    assert bobs["log"][-1]["author_user_id"] == ada.id
    cats = (await db_client.get(f"{moved}/KUN-2", headers=ada.headers)).json()
    assert cats["assignee_user_id"] == cat.id  # still in the workspace

    audit = (await db_client.get(f"/v1/workspaces/{two['id']}/audit", headers=ada.headers)).json()
    moved_in = next(e for e in audit if e["action"] == "project.moved_in")
    assert moved_in["details"]["unassigned"] == 1 and moved_in["details"]["watchers_removed"] == 1


async def test_status_and_target_date(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    cat = await signup(email="cat@example.com", name="Cat")
    team = await create_team(ada.headers)
    await add_member(team["id"], cat.id, Role.MEMBER)
    project = (await db_client.post(projects_url(team), json={"key": "KUN", "name": "K"}, headers=ada.headers)).json()
    assert project["health"] is None and project["target_date"] is None
    url = f"{projects_url(team)}/{project['id']}"
    res = await db_client.patch(url, json={"health": "at_risk", "target_date": "2026-12-01"}, headers=ada.headers)
    assert res.status_code == 200 and (res.json()["health"], res.json()["target_date"]) == ("at_risk", "2026-12-01")
    # Leaving them out keeps them; null clears.
    assert (await db_client.patch(url, json={"name": "Kunemi"}, headers=ada.headers)).json()["health"] == "at_risk"
    cleared = (await db_client.patch(url, json={"health": None, "target_date": None}, headers=ada.headers)).json()
    assert cleared["health"] is None and cleared["target_date"] is None
    assert (await db_client.patch(url, json={"health": "sideways"}, headers=ada.headers)).status_code == 422
    # Members see it, but don't set it.
    assert (await db_client.patch(url, json={"health": "on_track"}, headers=cat.headers)).status_code == 403


async def test_lifecycle_icon_and_colour(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    cat = await signup(email="cat@example.com", name="Cat")
    team = await create_team(ada.headers)
    await add_member(team["id"], cat.id, Role.MEMBER)
    plain = (await db_client.post(projects_url(team), json={"key": "KUN", "name": "K"}, headers=ada.headers)).json()
    # By default: active, and it looks like its key (no icon, colour from the key).
    assert (plain["status"], plain["icon"], plain["color"]) == ("active", None, None)
    styled = await db_client.post(
        projects_url(team), json={"key": "WEB", "name": "Web", "icon": "globe", "color": "teal"}, headers=ada.headers
    )
    assert styled.status_code == 201 and (styled.json()["icon"], styled.json()["color"]) == ("globe", "teal")

    url = f"{projects_url(team)}/{plain['id']}"
    res = await db_client.patch(url, json={"status": "on_hold", "icon": "rocket", "color": "rose"}, headers=ada.headers)
    assert res.status_code == 200
    assert (res.json()["status"], res.json()["icon"], res.json()["color"]) == ("on_hold", "rocket", "rose")
    # Leaving them out keeps them; null puts the key's look back.
    kept = (await db_client.patch(url, json={"name": "Kunemi"}, headers=ada.headers)).json()
    assert (kept["status"], kept["icon"]) == ("on_hold", "rocket")
    back = (await db_client.patch(url, json={"icon": None, "color": None}, headers=ada.headers)).json()
    assert (back["icon"], back["color"], back["status"]) == (None, None, "on_hold")
    for bad in ({"icon": "skull"}, {"color": "plaid"}, {"status": "sideways"}):
        assert (await db_client.patch(url, json=bad, headers=ada.headers)).status_code == 422
    assert (await db_client.patch(url, json={"status": "completed"}, headers=cat.headers)).status_code == 403


async def test_stars_are_per_person_and_follow_what_you_can_see(
    signup, create_team, add_member, db_client: AsyncClient
) -> None:
    ada = await signup()
    cat = await signup(email="cat@example.com", name="Cat")
    team = await create_team(ada.headers)
    await add_member(team["id"], cat.id, Role.MEMBER)
    url = projects_url(team)
    kun = (await db_client.post(url, json={"key": "KUN", "name": "K"}, headers=ada.headers)).json()
    mob = (await db_client.post(url, json={"key": "MOB", "name": "M"}, headers=ada.headers)).json()
    assert (await db_client.get(f"{url}/starred", headers=cat.headers)).json() == []

    for project in (mob, kun):
        assert (await db_client.put(f"{url}/{project['id']}/star", headers=cat.headers)).status_code == 204
    await db_client.put(f"{url}/{mob['id']}/star", headers=cat.headers)  # starring twice is fine
    assert (await db_client.get(f"{url}/starred", headers=cat.headers)).json() == [mob["id"], kun["id"]]
    assert (await db_client.get(f"{url}/starred", headers=ada.headers)).json() == []  # nobody else's

    # Restricted without Cat on it: it drops out of Cat's stars.
    await db_client.patch(f"{url}/{mob['id']}", json={"access": "restricted"}, headers=ada.headers)
    assert (await db_client.get(f"{url}/starred", headers=cat.headers)).json() == [kun["id"]]
    assert (await db_client.delete(f"{url}/{kun['id']}/star", headers=cat.headers)).status_code == 204
    assert (await db_client.delete(f"{url}/{kun['id']}/star", headers=cat.headers)).status_code == 204
    assert (await db_client.get(f"{url}/starred", headers=cat.headers)).json() == []


async def test_archive_restore_and_delete_a_project(signup, create_team, add_member, db_client: AsyncClient, storage) -> None:
    ada = await signup()
    team = await create_team(ada.headers)
    url = projects_url(team)
    project = (await db_client.post(url, json={"key": "OLD", "name": "Old"}, headers=ada.headers)).json()
    base = f"{url}/{project['id']}"
    await db_client.post(f"{base}/issues", json={"title": "Leftover"}, headers=ada.headers)
    await db_client.post(f"{base}/documents", files={"file": ("notes.md", b"# Notes\n", "text/markdown")}, headers=ada.headers)

    archived = await db_client.patch(base, json={"archived": True}, headers=ada.headers)
    assert archived.status_code == 200 and archived.json()["archived_at"] is not None
    restored = await db_client.patch(base, json={"archived": False}, headers=ada.headers)
    assert restored.json()["archived_at"] is None

    grace = await signup(email="grace@example.com", name="Grace")
    await add_member(team["id"], grace.id, Role.MEMBER)
    assert (await db_client.delete(base, headers=grace.headers)).status_code == 403

    assert (await db_client.delete(base, headers=ada.headers)).status_code == 204
    assert (await db_client.get(base, headers=ada.headers)).status_code == 404
    assert storage.objects == {}  # its files went with it
    audit = (await db_client.get(f"/v1/workspaces/{team['id']}/audit", headers=ada.headers)).json()
    actions = [a["action"] for a in audit]
    assert "project.deleted" in actions and "project.archived" in actions  # its history stays
