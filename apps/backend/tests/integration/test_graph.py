"""The project graph (agents v2 step 3): links derived from issues and documents, kept current,
walked for neighbours, impact, paths, and stale documents."""
from httpx import AsyncClient

from pmagent_backend.modules.workspaces.models import Role


async def _world(db_client: AsyncClient, signup, create_team, add_member):
    ada = await signup()
    cat = await signup(email="cat@example.com", name="Cat")
    team = await create_team(ada.headers)
    await add_member(team["id"], cat.id, Role.MEMBER)
    ws = f"/v1/workspaces/{team['id']}"
    project = (await db_client.post(f"{ws}/projects", json={"key": "KUN", "name": "K"}, headers=ada.headers)).json()
    return ada, cat, ws, f"{ws}/projects/{project['id']}"


async def _write(db_client: AsyncClient, base: str, path: str, content: str, headers) -> None:
    res = await db_client.put(f"{base}/knowledge/files/{path}", json={"content": content}, headers=headers)
    assert res.status_code in (200, 201), res.text


async def _issue(db_client: AsyncClient, base: str, headers, **body) -> str:
    res = await db_client.post(f"{base}/issues", json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()["key"]


def _links(neighbors: dict) -> set[tuple[str, str, str]]:
    return {(link["direction"], link["kind"], link["node"]["ref"]) for link in neighbors["links"]}


async def test_the_graph_follows_issues_and_documents(
    db_client: AsyncClient, signup, create_team, add_member
) -> None:
    ada, cat, _, base = await _world(db_client, signup, create_team, add_member)
    await _write(db_client, base, "requirements/auth.md", "# Sign-in\n\nPeople sign in with email.\n", ada.headers)
    await _write(db_client, base, "decisions/ADR-001.md",
                 "# ADR-001: Sessions in cookies\n\n- Affected modules: auth, web proxy\n\nFor requirements/auth.md.\n",
                 ada.headers)
    epic = await _issue(db_client, base, ada.headers, type="epic", title="Accounts")
    story = await _issue(db_client, base, ada.headers, type="story", title="Sign in", parent=epic,
                         description="Implements requirements/auth.md, following ADR-1.")
    task = await _issue(db_client, base, ada.headers, type="task", title="Login form", depends_on=[story])
    graph = f"{base}/graph"

    story_links = (await db_client.get(f"{graph}/neighbors", params={"ref": story.lower()}, headers=cat.headers)).json()
    assert _links(story_links) == {
        ("out", "part_of", epic), ("out", "implements", "requirements/auth.md"),
        ("out", "decided_by", "decisions/ADR-001.md"), ("in", "depends_on", task),
    }
    adr = (await db_client.get(f"{graph}/neighbors", params={"ref": "/pmagent/decisions/ADR-001.md"},
                               headers=cat.headers)).json()
    assert {("out", "affects", "module:auth"), ("out", "affects", "module:web proxy"),
            ("out", "mentions", "requirements/auth.md")} <= _links(adr)

    # What changing the requirement affects: the story and the decision built on it, then the task
    # waiting for the story and the decision's modules; not the epic the story sits under.
    impact = (await db_client.get(f"{graph}/impact", params={"ref": "requirements/auth.md", "depth": 2},
                                  headers=cat.headers)).json()
    affected = {(i["node"]["ref"], i["depth"]) for i in impact["affected"]}
    assert {(story, 1), ("decisions/ADR-001.md", 1), (task, 2)} <= affected
    assert ("module:auth", 2) in affected  # through the decision
    assert epic not in {ref for ref, _ in affected}

    path = (await db_client.get(f"{graph}/path", params={"from": task, "to": "module:auth"}, headers=cat.headers)).json()
    assert path["found"] and [s["node"]["ref"] for s in path["steps"]] == [
        task, story, "decisions/ADR-001.md", "module:auth"
    ]
    assert (await db_client.get(f"{graph}/neighbors", params={"ref": "KUN-99"}, headers=cat.headers)).status_code == 404

    # Kept current: the description changes, the links follow; a link to a document that
    # doesn't exist yet appears when it does.
    await db_client.patch(f"{base}/issues/{story}", json={"description": "Per requirements/sso.md now."}, headers=ada.headers)
    assert ("out", "implements", "requirements/auth.md") not in _links(
        (await db_client.get(f"{graph}/neighbors", params={"ref": story}, headers=cat.headers)).json())
    await _write(db_client, base, "requirements/sso.md", "# SSO\n", ada.headers)
    assert ("out", "implements", "requirements/sso.md") in _links(
        (await db_client.get(f"{graph}/neighbors", params={"ref": story}, headers=cat.headers)).json())


async def test_stale_documents_and_links_by_hand(
    db_client: AsyncClient, signup, create_team, add_member
) -> None:
    ada, cat, ws, base = await _world(db_client, signup, create_team, add_member)
    graph = f"{base}/graph"
    await _write(db_client, base, "decisions/ADR-001.md", "# ADR-001: REST\n", ada.headers)
    story = await _issue(db_client, base, ada.headers, type="task", title="Export", description="Per ADR-1")
    await _write(db_client, base, "architecture/overview.md", f"# Overview\n\nSee decisions/ADR-001.md and {story}.\n",
                 ada.headers)
    assert (await db_client.get(f"{graph}/stale", headers=cat.headers)).json() == []

    await _write(db_client, base, "decisions/ADR-002.md", "# ADR-002: GraphQL\n\n- Supersedes: ADR-001\n", ada.headers)
    await _write(db_client, base, "decisions/ADR-001.md", "# ADR-001: REST\n\nStill REST for webhooks.\n", ada.headers)
    await db_client.patch(f"{base}/issues/{story}", json={"status": "done"}, headers=ada.headers)
    stale = {s["node"]["ref"]: s["reasons"] for s in (await db_client.get(f"{graph}/stale", headers=cat.headers)).json()}
    assert set(stale["architecture/overview.md"]) == {
        "decisions/ADR-001.md changed since", f"{story} (Export) was finished since"
    }
    assert set(stale["decisions/ADR-001.md"]) == {
        "superseded by decisions/ADR-002.md", f"{story} (Export), which builds on it, was finished since"
    }

    # Links by hand: people who may edit documents; audited; derived links can't be removed.
    body = {"source": "architecture/overview.md", "target": "decisions/ADR-002.md", "kind": "relates_to",
            "reason": "The API section follows it"}
    assert (await db_client.post(f"{graph}/links", json=body, headers=cat.headers)).status_code == 403
    made = await db_client.post(f"{graph}/links", json=body, headers=ada.headers)
    assert made.status_code == 201, made.text
    link = next(link for link in made.json()["links"] if link["kind"] == "relates_to")
    assert link["origin"] == "person" and link["reason"] == "The API section follows it"
    assert (await db_client.post(f"{graph}/links", json=body, headers=ada.headers)).status_code == 409
    assert (await db_client.post(f"{graph}/links", json={**body, "kind": "depends_on"}, headers=ada.headers)).status_code == 422
    derived = next(link for link in made.json()["links"] if link["origin"] == "derived")
    assert (await db_client.delete(f"{graph}/links/{derived['id']}", headers=ada.headers)).status_code == 409
    assert (await db_client.delete(f"{graph}/links/{link['id']}", headers=ada.headers)).status_code == 204
    actions = {e["action"] for e in (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()}
    assert {"graph.linked", "graph.unlinked"} <= actions


async def test_agents_read_the_graph_and_link_with_approval(
    db_client: AsyncClient, signup, create_team, add_member, agent_script
) -> None:
    from pmagent_engine.testing import tool_call

    ada, _, _, base = await _world(db_client, signup, create_team, add_member)
    await _write(db_client, base, "requirements/auth.md", "# Sign-in\n", ada.headers)
    story = await _issue(db_client, base, ada.headers, type="task", title="Login", description="requirements/auth.md")
    model = agent_script.say(
        tool_call("graph_impact", ref="requirements/auth.md"),
        tool_call("link_items", source="requirements/auth.md", target="project.md", kind="relates_to",
                  reason="The goals come from it"),
        "Linked.",
    )
    run = (await db_client.post(f"{base}/agent/runs", json={"message": "what relies on auth?"}, headers=ada.headers)).json()
    impact_result = next(m.content for m in model.received[1] if getattr(m, "name", None) == "graph_impact")
    assert f"implements: {story} (task, todo): Login" in impact_result
    assert run["status"] == "awaiting_approval"
    approval = run["approvals"][0]
    assert approval["tool"] == "link_items" and approval["target"] == "link: requirements/auth.md relates to project.md"
    done = (await db_client.post(f"{base}/agent/runs/{run['id']}/decisions", headers=ada.headers, json={
        "decisions": [{"approval_id": approval["id"], "decision": "approve"}]
    })).json()
    assert done["status"] == "completed"
    links = (await db_client.get(f"{base}/graph/neighbors", params={"ref": "project.md"}, headers=ada.headers)).json()
    added = next(link for link in links["links"] if link["kind"] == "relates_to")
    assert added["origin"] == "agent" and added["agent"] == "project-manager" and added["reason"] == "The goals come from it"
