"""Cross-workspace isolation (NFR multi-tenancy): nothing in one workspace is reachable from
another, whatever IDs a caller knows.

The route checks are generated from the app's own routes, so a new workspace or project route
is covered automatically. If a new route has a path parameter this file
doesn't know, `test_every_scoped_route_is_covered` fails: add a value to `World.params`.
"""
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import AsyncClient

from pmagent_engine.testing import tool_call

SCOPES = ("{workspace_id}",)


@dataclass
class World:
    """One person's workspace with one of everything in it."""

    headers: dict[str, str]
    params: dict[str, str]
    colleague_headers: dict[str, str]  # a member of the workspace, not added to the restricted project
    restricted_id: str  # a restricted project nobody was added to


@pytest.fixture
def build_world(db_client: AsyncClient, signup, create_team, add_member, agent_script):
    async def _build(email: str, name: str) -> World:
        owner = await signup(email=email, name=name)
        h = owner.headers
        team = await create_team(h, name=f"{name}'s team")
        ws = f"/v1/workspaces/{team['id']}"
        # Same project key and issue key in every world, so keys alone never identify one.
        project = (await db_client.post(f"{ws}/projects", json={"key": "KUN", "name": "K"}, headers=h)).json()
        base = f"{ws}/projects/{project['id']}"
        issue = await db_client.post(f"{base}/issues", json={"type": "task", "title": "x"}, headers=h)
        assert issue.status_code == 201, issue.text
        document = await db_client.post(
            f"{base}/documents", files={"file": ("notes.md", b"# Notes\n", "text/markdown")}, headers=h
        )
        assert document.status_code == 201, document.text
        invite = await db_client.post(f"{ws}/invites", json={"email": f"guest-{email}", "role": "member"}, headers=h)
        assert invite.status_code == 201, invite.text
        colleague = await signup(email=f"colleague-{email}", name="Colleague")
        await add_member(team["id"], colleague.id, "member")
        restricted = await db_client.post(
            f"{ws}/projects", json={"key": "SEC", "name": "Secret", "access": "restricted"}, headers=h
        )
        assert restricted.status_code == 201, restricted.text
        token = (await db_client.post("/v1/me/tokens", json={"name": "script"}, headers=h)).json()
        automation = await db_client.post(
            f"{base}/automations", json={"name": "Daily", "instructions": "Summarise.", "schedule_hour": 6}, headers=h
        )
        assert automation.status_code == 201, automation.text
        params = {
            "workspace_id": team["id"],
            "project_id": project["id"],
            "key": issue.json()["key"],
            "issue_id": issue.json()["id"],  # (not a path parameter; for comparisons)
            "path": "requirements/product.md",
            "version": "1",
            "document_id": document.json()["id"],
            "invite_id": invite.json()["id"],
            "user_id": colleague.id,
            "token_id": token["id"],
            "handle": "product",
            "output_id": "01a0e000-0000-7000-8000-000000000000",
            "index": "0",
            "installation_ref": "01a0e000-0000-7000-8000-000000000000",
            "automation_id": automation.json()["id"],
        }
        # A run paused on an approval: it has a run, a thread, and a pending action.
        agent_script.say(tool_call("write_file", file_path="/pmagent/roadmap.md", content="# R\n"), "Done.")
        run = (await db_client.post(f"{base}/agent/runs", json={"message": "Plan"}, headers=h)).json()
        assert run["status"] == "awaiting_approval", run
        params |= {"run_id": run["id"], "thread_id": run["thread_id"]}
        # A rejected change with a reason: a proposed lesson.
        agent_script.say(tool_call("write_file", file_path="/pmagent/vision.md", content="# V\n"), "Fine.")
        other = (await db_client.post(f"{base}/agent/runs", json={"message": "Vision"}, headers=h)).json()
        await db_client.post(f"{base}/agent/runs/{other['id']}/decisions", headers=h, json={"decisions": [
            {"approval_id": a["id"], "decision": "reject", "reason": "Too vague"} for a in other["approvals"]
        ]})
        lessons = (await db_client.get(f"{base}/lessons", headers=h)).json()
        assert len(lessons) == 1, lessons
        link = await db_client.post(f"{base}/graph/links", headers=h,
                                    json={"source": issue.json()["key"], "target": "project.md"})
        assert link.status_code == 201, link.text
        params["link_id"] = next(lk["id"] for lk in link.json()["links"] if lk["origin"] == "person")
        params |= {"lesson_id": lessons[0]["id"], "rejected_run_id": other["id"]}  # (not a path parameter)
        return World(
            headers=h, params=params, colleague_headers=colleague.headers, restricted_id=restricted.json()["id"]
        )

    return _build


def _scoped_routes(client: AsyncClient) -> list[tuple[str, str, bool]]:
    """(method, path template, takes a body) for every workspace route, from
    the OpenAPI schema (the API's contract)."""
    app = client._transport.app  # type: ignore[attr-defined]
    routes = []
    for path, operations in app.openapi()["paths"].items():
        if any(scope in path for scope in SCOPES):
            for method, operation in operations.items():
                if method in {"get", "post", "put", "patch", "delete"}:
                    routes.append((method.upper(), path, "requestBody" in operation))
    return routes


def _fill(template: str, params: dict[str, str]) -> str:
    path = template
    for name, value in params.items():
        path = path.replace(f"{{{name}}}", value)
    return path


# Valid bodies for routes that would otherwise fail validation (422) before looking anything
# up. Routes resolve the workspace and project in dependencies, before the body; these look
# their resource up in the service, after it.
BODIES: dict[tuple[str, str], dict[str, Any]] = {
    ("PATCH", "/v1/workspaces/{workspace_id}/members/{user_id}"): {"role": "admin"},
    ("PATCH", "/v1/workspaces/{workspace_id}/projects/{project_id}/agent/threads/{thread_id}"): {"title": "x"},
    ("PATCH", "/v1/workspaces/{workspace_id}/projects/{project_id}/agent/runs/{run_id}/outputs/{output_id}/items/{index}"): {
        "state": "dismissed"
    },
    ("POST", "/v1/workspaces/{workspace_id}/github/installations"): {"installation_id": 1, "code": "x"},
    ("PUT", "/v1/workspaces/{workspace_id}/projects/{project_id}/repository"): {
        "installation_ref": "01a0e000-0000-7000-8000-000000000000", "github_repo_id": 1
    },
    ("POST", "/v1/workspaces/{workspace_id}/projects/{project_id}/agent/runs/{run_id}/decisions"): {
        "decisions": [{"approval_id": "01a0e000-0000-7000-8000-000000000000", "decision": "approve"}]
    },
}


async def _call(client: AsyncClient, method: str, url: str, body: bool, headers: dict[str, str], template: str = "") -> int:
    json = BODIES.get((method, template), {}) if body else None
    res = await client.request(method, url, json=json, headers=headers)
    return res.status_code


async def test_every_scoped_route_is_covered(db_client: AsyncClient) -> None:
    known = {"workspace_id", "project_id", "key", "path", "version", "document_id", "invite_id",
             "user_id", "run_id", "thread_id", "handle", "output_id", "index", "installation_ref", "automation_id",
             "lesson_id", "link_id"}
    routes = _scoped_routes(db_client)
    assert len(routes) > 60  # sanity: the whole API is being walked
    for _, template, _ in routes:
        names = {part.strip("{}") for part in template.split("/") if part.startswith("{")}
        assert names <= known, f"{template}: add a value for {names - known} to World.params"


async def test_outsiders_get_404_from_every_route_with_real_ids(db_client: AsyncClient, build_world) -> None:
    ada = await build_world("ada@example.com", "Ada")
    mallory = await build_world("mallory@example.com", "Mallory")
    leaks = []
    for method, template, body in _scoped_routes(db_client):
        url = _fill(template, ada.params)
        status = await _call(db_client, method, url, body, mallory.headers)
        if status != 404:
            leaks.append(f"{method} {template} -> {status}")
    assert leaks == []


async def test_ids_from_another_workspace_dont_work_in_your_own(db_client: AsyncClient, build_world) -> None:
    """Mallory owns her workspace, so she passes every permission check there; each of Ada's
    IDs, used under Mallory's workspace (and project), must still be not found."""
    ada = await build_world("ada@example.com", "Ada")
    mallory = await build_world("mallory@example.com", "Mallory")
    mixed_in = ["project_id", "document_id", "run_id", "thread_id", "invite_id", "user_id"]
    leaks = []
    for method, template, body in _scoped_routes(db_client):
        if "{workspace_id}" not in template:
            continue
        for name in mixed_in:
            if f"{{{name}}}" not in template:
                continue
            params = mallory.params | {name: ada.params[name]}
            status = await _call(db_client, method, _fill(template, params), body, mallory.headers, template)
            if status != 404:
                leaks.append(f"{method} {template} with Ada's {name} -> {status}")
    assert leaks == []


async def test_lists_show_only_your_own(db_client: AsyncClient, build_world) -> None:
    ada = await build_world("ada@example.com", "Ada")
    mallory = await build_world("mallory@example.com", "Mallory")
    h, ws = mallory.headers, f"/v1/workspaces/{mallory.params['workspace_id']}"

    workspaces = (await db_client.get("/v1/workspaces", headers=h)).json()
    assert ada.params["workspace_id"] not in {w["id"] for w in workspaces}
    tokens = (await db_client.get("/v1/me/tokens", headers=h)).json()
    assert ada.params["token_id"] not in {t["id"] for t in tokens}
    assert (await db_client.delete(f"/v1/me/tokens/{ada.params['token_id']}", headers=h)).status_code == 404

    approvals = (await db_client.get(f"{ws}/approvals", headers=h)).json()
    assert {a["run_id"] for a in approvals} == {mallory.params["run_id"]}
    audit = (await db_client.get(f"{ws}/audit", headers=h)).json()
    assert ada.params["workspace_id"] not in str(audit) and "ada@example.com" not in str(audit)
    projects = (await db_client.get(f"{ws}/projects", headers=h)).json()
    assert [p["id"] for p in projects] == [mallory.params["project_id"], mallory.restricted_id]
    base = f"{ws}/projects/{mallory.params['project_id']}"
    runs = (await db_client.get(f"{base}/agent/runs", headers=h)).json()
    assert {r["id"] for r in runs} == {mallory.params["run_id"], mallory.params["rejected_run_id"]}
    assert [d["id"] for d in (await db_client.get(f"{base}/documents", headers=h)).json()] == [
        mallory.params["document_id"]
    ]
    # Mallory's KUN-1 is her own issue, not Ada's.
    issue = (await db_client.get(f"{base}/issues/KUN-1", headers=h)).json()
    assert issue["id"] == mallory.params["issue_id"] != ada.params["issue_id"]


async def test_a_restricted_project_is_404_to_a_member_not_added(db_client: AsyncClient, build_world) -> None:
    ada = await build_world("ada@example.com", "Ada")
    """Answered exactly as for a project that doesn't exist: 404, or a 403 from the role check
    that runs before any project is looked up."""
    params = ada.params | {"project_id": ada.restricted_id}
    missing = ada.params | {"project_id": "01a0e000-0000-7000-8000-00000000dead"}
    leaks = []
    for method, template, body in _scoped_routes(db_client):
        if "{project_id}" not in template:
            continue
        status = await _call(db_client, method, _fill(template, params), body, ada.colleague_headers, template)
        expected = await _call(db_client, method, _fill(template, missing), body, ada.colleague_headers, template)
        if status not in (403, 404) or status != expected:
            leaks.append(f"{method} {template} -> {status} (missing project: {expected})")
    assert leaks == []
    ws = f"/v1/workspaces/{ada.params['workspace_id']}"
    listed = (await db_client.get(f"{ws}/projects", headers=ada.colleague_headers)).json()
    assert [p["key"] for p in listed] == ["KUN"]
    # Its owner sees both.
    assert [p["key"] for p in (await db_client.get(f"{ws}/projects", headers=ada.headers)).json()] == ["KUN", "SEC"]
