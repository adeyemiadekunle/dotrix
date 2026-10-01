from datetime import date

import pytest
from httpx import AsyncClient

from pmagent_backend.modules.workspaces.models import Role


@pytest.fixture
def project(db_client: AsyncClient, create_team, signup):
    async def _make():
        ada = await signup()
        team = await create_team(ada.headers)
        created = (
            await db_client.post(
                f"/v1/workspaces/{team['id']}/projects", json={"key": "KUN", "name": "Kunemi"},
                headers=ada.headers,
            )
        ).json()
        return ada, team, f"/v1/workspaces/{team['id']}/projects/{created['id']}/issues"

    return _make


async def new(client: AsyncClient, url: str, headers, **body) -> dict:
    body.setdefault("title", "Something")
    if body.get("type") in ("story", "bug"):
        body.setdefault("description", "Acceptance: it works.")
    res = await client.post(url, json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


async def patch(client: AsyncClient, url: str, key: str, headers, **body):
    return await client.patch(f"{url}/{key}", json=body, headers=headers)


# -- create, keys, hierarchy ------------------------------------------------------------


async def test_keys_are_sequential_and_logged(project, db_client: AsyncClient) -> None:
    ada, _, url = await project()
    first = await new(db_client, url, ada.headers, title="Build hub model")
    second = await new(db_client, url, ada.headers, title="Driver routing", priority="high")
    assert (first["key"], second["key"]) == ("KUN-1", "KUN-2")
    assert first["reporter_user_id"] == ada.id and first["watchers"] == [ada.id]
    assert first["status"] == "todo" and first["ready"] is True
    assert [e["kind"] for e in first["log"]] == ["created"]
    # Keys are case-insensitive in URLs.
    assert (await db_client.get(f"{url}/kun-2", headers=ada.headers)).json()["title"] == "Driver routing"


async def test_parent_rules(project, db_client: AsyncClient) -> None:
    ada, _, url = await project()
    epic = await new(db_client, url, ada.headers, type="epic", title="Scheduled delivery")
    story = await new(db_client, url, ada.headers, type="story", parent=epic["key"])
    task = await new(db_client, url, ada.headers, type="task")
    sub = await new(db_client, url, ada.headers, type="sub-task", parent=story["key"])
    assert story["parent_key"] == epic["key"] and sub["parent_key"] == story["key"]

    bad = [
        {"type": "sub-task"},  # needs a parent
        {"type": "story", "parent": task["key"]},  # stories sit under epics
        {"type": "epic", "parent": epic["key"]},  # epics have no parent
        {"type": "sub-task", "parent": sub["key"]},  # no sub-sub-tasks
        {"type": "task", "parent": "KUN-999"},  # unknown parent
    ]
    for body in bad:
        res = await db_client.post(url, json={"title": "x", "description": "d", **body}, headers=ada.headers)
        assert res.status_code in (404, 422), body

    # Changing a type must keep its children valid.
    res = await patch(db_client, url, story["key"], ada.headers, type="epic")
    assert res.status_code == 422
    detail = (await db_client.get(f"{url}/{epic['key']}", headers=ada.headers)).json()
    assert detail["children"] == [story["key"]]


async def test_stories_and_bugs_need_a_description(project, db_client: AsyncClient) -> None:
    ada, _, url = await project()
    for issue_type in ("story", "bug"):
        res = await db_client.post(url, json={"type": issue_type, "title": "x"}, headers=ada.headers)
        assert res.status_code == 422 and res.json()["type"].endswith("/invalid_issue")
    story = await new(db_client, url, ada.headers, type="story")
    assert (await patch(db_client, url, story["key"], ada.headers, description="  ")).status_code == 422


# -- updates and the log ----------------------------------------------------------------


async def test_updates_are_logged(project, db_client: AsyncClient) -> None:
    ada, _, url = await project()
    issue = await new(db_client, url, ada.headers, title="Hub model")
    res = await patch(
        db_client, url, issue["key"], ada.headers,
        priority="urgent", labels=["core", "core", " db "], due="2026-10-09", note="Needed for launch",
    )
    body = res.json()
    assert body["priority"] == "urgent" and body["labels"] == ["core", "db"] and body["due"] == "2026-10-09"
    last = body["log"][-1]
    assert last["kind"] == "updated" and last["body"] == "Needed for launch"
    assert last["changes"]["priority"] == ["medium", "urgent"]

    done = (await patch(db_client, url, issue["key"], ada.headers, status="done")).json()
    assert done["resolved_at"] is not None
    reopened = (await patch(db_client, url, issue["key"], ada.headers, status="todo")).json()
    assert reopened["resolved_at"] is None
    # Sending nothing new records nothing.
    count = len(reopened["log"])
    assert len((await patch(db_client, url, issue["key"], ada.headers, status="todo")).json()["log"]) == count


async def test_comments(project, db_client: AsyncClient) -> None:
    ada, _, url = await project()
    issue = await new(db_client, url, ada.headers)
    res = await db_client.post(f"{url}/{issue['key']}/comments", json={"body": "Schema drafted"}, headers=ada.headers)
    assert res.status_code == 201
    assert res.json()["log"][-1] == res.json()["log"][-1] | {"kind": "commented", "body": "Schema drafted"}


# -- dependencies and readiness ----------------------------------------------------------


async def test_dependencies_and_readiness(project, db_client: AsyncClient) -> None:
    ada, _, url = await project()
    api = await new(db_client, url, ada.headers, title="Postcode API")
    lookup = await new(db_client, url, ada.headers, title="Postcode lookup", depends_on=[api["key"]])
    assert lookup["depends_on"] == [api["key"]] and lookup["ready"] is False
    assert (await db_client.get(f"{url}/{api['key']}", headers=ada.headers)).json()["blocks"] == [lookup["key"]]

    ready = (await db_client.get(url, params={"ready": True}, headers=ada.headers)).json()
    assert [i["key"] for i in ready] == [api["key"]]
    await patch(db_client, url, api["key"], ada.headers, status="done")
    assert (await db_client.get(f"{url}/{lookup['key']}", headers=ada.headers)).json()["ready"] is True


async def test_dependency_validation(project, db_client: AsyncClient) -> None:
    ada, _, url = await project()
    a = await new(db_client, url, ada.headers, title="A")
    b = await new(db_client, url, ada.headers, title="B", depends_on=[a["key"]])
    c = await new(db_client, url, ada.headers, title="C", depends_on=[b["key"]])

    cycle = await patch(db_client, url, a["key"], ada.headers, depends_on=[c["key"]])  # A→C→B→A
    assert cycle.status_code == 422 and cycle.json()["type"].endswith("/dependency_cycle")
    assert (await patch(db_client, url, a["key"], ada.headers, depends_on=[a["key"]])).status_code == 422
    assert (await patch(db_client, url, a["key"], ada.headers, depends_on=["KUN-404"])).status_code == 422
    # Replacing a list is fine, and clearing it too.
    assert (await patch(db_client, url, c["key"], ada.headers, depends_on=[a["key"]])).json()["depends_on"] == [a["key"]]
    assert (await patch(db_client, url, c["key"], ada.headers, depends_on=[])).json()["depends_on"] == []


# -- next and claim ---------------------------------------------------------------------


async def test_next_orders_by_priority_then_due_then_age(project, db_client: AsyncClient) -> None:
    ada, _, url = await project()
    await new(db_client, url, ada.headers, title="low", priority="low")
    await new(db_client, url, ada.headers, title="high later", priority="high", due="2026-12-01")
    await new(db_client, url, ada.headers, title="high sooner", priority="high", due="2026-10-01")
    await new(db_client, url, ada.headers, type="epic", title="epics are never next", priority="urgent")
    nxt = (await db_client.get(f"{url}/next", headers=ada.headers)).json()
    assert nxt["title"] == "high sooner"


async def test_claim_and_resume(project, db_client: AsyncClient) -> None:
    ada, _, url = await project()
    first = await new(db_client, url, ada.headers, title="First", priority="high")
    await new(db_client, url, ada.headers, title="Second")

    claimed = (await db_client.post(f"{url}/claim", json={}, headers=ada.headers)).json()
    assert claimed["key"] == first["key"] and claimed["status"] == "in_progress"
    assert claimed["assignee_user_id"] == ada.id and claimed["log"][-1]["kind"] == "claimed"
    # `next` returns your in-progress issue first, so a crashed session resumes it.
    assert (await db_client.get(f"{url}/next", headers=ada.headers)).json()["key"] == first["key"]
    # A claimed issue can't be claimed again.
    again = await db_client.post(f"{url}/claim", json={"key": first["key"]}, headers=ada.headers)
    assert again.status_code == 409


async def test_nothing_ready(project, db_client: AsyncClient) -> None:
    ada, _, url = await project()
    res = await db_client.post(f"{url}/claim", json={}, headers=ada.headers)
    assert res.status_code == 404 and res.json()["type"].endswith("/nothing_ready")


async def test_issues_assigned_to_others_are_not_claimable(
    project, db_client: AsyncClient, add_member, signup
) -> None:
    ada, team, url = await project()
    bob = await signup(email="bob@example.com", name="Bob")
    await add_member(team["id"], bob.id, Role.MEMBER)
    await new(db_client, url, ada.headers, title="Bob's", assignee_user_id=bob.id)
    assert (await db_client.post(f"{url}/claim", json={}, headers=ada.headers)).status_code == 404
    assert (await db_client.post(f"{url}/claim", json={}, headers=bob.headers)).json()["title"] == "Bob's"


# -- coding tools (as_agent) --------------------------------------------------------------


async def test_coding_tool_workflow(project, db_client: AsyncClient) -> None:
    ada, _, url = await project()
    issue = await new(db_client, url, ada.headers, title="Build postcode lookup")
    other = await new(db_client, url, ada.headers, title="Someone else's")
    await patch(db_client, url, other["key"], ada.headers, assignee_agent="codex")

    claimed = (
        await db_client.post(f"{url}/claim", json={"key": issue["key"], "as_agent": "claude-code"}, headers=ada.headers)
    ).json()
    assert claimed["assignee_agent"] == "claude-code" and claimed["assignee_user_id"] is None
    assert claimed["log"][-1]["author_agent"] == "claude-code"
    nxt = (await db_client.get(f"{url}/next", params={"as_agent": "claude-code"}, headers=ada.headers)).json()
    assert nxt["key"] == issue["key"]

    agent = {"as_agent": "claude-code"}
    # It can comment, add sub-tasks, link a PR, and hand back for review...
    ok = await db_client.post(f"{url}/{issue['key']}/comments", json={"body": "PR open", **agent}, headers=ada.headers)
    assert ok.status_code == 201
    sub = await new(db_client, url, ada.headers, type="sub-task", parent=issue["key"], **agent)
    assert sub["reporter_agent"] == "claude-code"
    review = await patch(
        db_client, url, issue["key"], ada.headers, status="review",
        links=[{"kind": "pr", "url": "https://github.com/x/y/pull/7"}], **agent,
    )
    assert review.status_code == 200 and review.json()["status"] == "review"
    # ...but never close it, change other fields, or touch issues that aren't its own.
    assert (await patch(db_client, url, issue["key"], ada.headers, status="done", **agent)).status_code == 403
    assert (await patch(db_client, url, issue["key"], ada.headers, title="x", **agent)).status_code == 403
    assert (await db_client.post(f"{url}/{other['key']}/comments", json={"body": "hi", **agent}, headers=ada.headers)).status_code == 403
    assert (await db_client.post(url, json={"title": "new task", **agent}, headers=ada.headers)).status_code == 403
    # A person closes it.
    assert (await patch(db_client, url, issue["key"], ada.headers, status="done")).json()["status"] == "done"


async def test_assigning_the_coding_agent_needs_permission(
    project, db_client: AsyncClient, add_member, signup
) -> None:
    ada, team, url = await project()
    bob = await signup(email="bob@example.com", name="Bob")
    await add_member(team["id"], bob.id, Role.MEMBER)
    issue = await new(db_client, url, ada.headers)
    # Members can't instruct the built-in coding agent (PRD default), owners can.
    assert (await patch(db_client, url, issue["key"], bob.headers, assignee_agent="coding-agent")).status_code == 403
    assert (await patch(db_client, url, issue["key"], ada.headers, assignee_agent="coding-agent")).status_code == 200
    # Members may hand work to Claude Code or Codex.
    assert (await patch(db_client, url, issue["key"], bob.headers, assignee_agent="codex")).status_code == 200


async def test_assignee_must_be_a_member(project, db_client: AsyncClient, signup) -> None:
    ada, _, url = await project()
    eve = await signup(email="eve@example.com", name="Eve")
    res = await db_client.post(url, json={"title": "x", "assignee_user_id": eve.id}, headers=ada.headers)
    assert res.status_code == 422
    both = await db_client.post(
        url, json={"title": "x", "assignee_user_id": ada.id, "assignee_agent": "codex"}, headers=ada.headers
    )
    assert both.status_code == 422


# -- board, backlog, epics, filters -------------------------------------------------------


async def test_board_backlog_and_rank(project, db_client: AsyncClient) -> None:
    ada, _, url = await project()
    a = await new(db_client, url, ada.headers, title="A")
    b = await new(db_client, url, ada.headers, title="B")
    c = await new(db_client, url, ada.headers, title="C")
    await patch(db_client, url, b["key"], ada.headers, status="in_progress")
    await patch(db_client, url, c["key"], ada.headers, status="done")

    board = (await db_client.get(f"{url}/board", headers=ada.headers)).json()
    columns = {col["status"]: [i["key"] for i in col["issues"]] for col in board["columns"]}
    assert list(columns) == ["todo", "in_progress", "blocked", "review", "done"]
    assert columns["todo"] == [a["key"]] and columns["in_progress"] == [b["key"]] and columns["done"] == [c["key"]]

    backlog = [i["key"] for i in (await db_client.get(f"{url}/backlog", headers=ada.headers)).json()]
    assert backlog == [a["key"], b["key"]]  # done is left out
    await db_client.post(f"{url}/{b['key']}/rank", json={"before": a["key"]}, headers=ada.headers)
    backlog = [i["key"] for i in (await db_client.get(f"{url}/backlog", headers=ada.headers)).json()]
    assert backlog == [b["key"], a["key"]]
    await db_client.post(f"{url}/{b['key']}/rank", json={"after": a["key"]}, headers=ada.headers)
    backlog = [i["key"] for i in (await db_client.get(f"{url}/backlog", headers=ada.headers)).json()]
    assert backlog == [a["key"], b["key"]]


async def test_epic_progress_and_filters(project, db_client: AsyncClient) -> None:
    ada, _, url = await project()
    epic = await new(db_client, url, ada.headers, type="epic", title="Scheduled delivery")
    s1 = await new(db_client, url, ada.headers, type="story", parent=epic["key"], labels=["api"])
    await new(db_client, url, ada.headers, type="story", parent=epic["key"], assignee_agent="codex")
    await new(db_client, url, ada.headers, type="bug", labels=["api"])
    await patch(db_client, url, s1["key"], ada.headers, status="done")

    [progress] = (await db_client.get(f"{url}/epics", headers=ada.headers)).json()
    assert progress == {"key": epic["key"], "title": "Scheduled delivery", "status": "todo",
                        "total": 2, "done": 1, "percent": 50}

    def keys(res) -> list[str]:
        return [i["key"] for i in res.json()]

    assert keys(await db_client.get(url, params={"label": "api"}, headers=ada.headers)) == ["KUN-2", "KUN-4"]
    assert keys(await db_client.get(url, params={"type": "bug"}, headers=ada.headers)) == ["KUN-4"]
    assert keys(await db_client.get(url, params={"assignee": "codex"}, headers=ada.headers)) == ["KUN-3"]
    assert keys(await db_client.get(url, params={"parent": epic["key"]}, headers=ada.headers)) == ["KUN-2", "KUN-3"]
    board = (await db_client.get(f"{url}/board", params={"epic": epic["key"]}, headers=ada.headers)).json()
    assert sum(len(c["issues"]) for c in board["columns"]) == 2


async def test_watchers(project, db_client: AsyncClient, add_member, signup) -> None:
    ada, team, url = await project()
    bob = await signup(email="bob@example.com", name="Bob")
    await add_member(team["id"], bob.id, Role.MEMBER)
    issue = await new(db_client, url, ada.headers)
    watched = (await db_client.put(f"{url}/{issue['key']}/watch", headers=bob.headers)).json()
    assert set(watched["watchers"]) == {ada.id, bob.id}
    unwatched = (await db_client.delete(f"{url}/{issue['key']}/watch", headers=bob.headers)).json()
    assert unwatched["watchers"] == [ada.id]


# -- permissions --------------------------------------------------------------------------


async def test_issue_permissions(project, db_client: AsyncClient, add_member, signup) -> None:
    ada, team, url = await project()
    guest = await signup(email="guest@example.com", name="Guest")
    eve = await signup(email="eve@example.com", name="Eve")
    await add_member(team["id"], guest.id, Role.GUEST)
    issue = await new(db_client, url, ada.headers)
    token = (
        await db_client.post("/v1/me/tokens", json={"name": "ro", "scopes": ["read"]}, headers=ada.headers)
    ).json()["token"]

    assert (await db_client.get(url, headers=eve.headers)).status_code == 404
    assert (await db_client.get(f"{url}/{issue['key']}", headers=guest.headers)).status_code == 404
    assert (await db_client.post(url, json={"title": "x"}, headers=guest.headers)).status_code == 403
    read_only = {"Authorization": f"Bearer {token}"}
    assert (await db_client.get(url, headers=read_only)).status_code == 200
    assert (await db_client.post(url, json={"title": "x"}, headers=read_only)).status_code == 403


async def test_due_dates_round_trip(project, db_client: AsyncClient) -> None:
    ada, _, url = await project()
    issue = await new(db_client, url, ada.headers, due=date(2026, 10, 9).isoformat(), scheduled="2026-10-08T09:00:00Z")
    assert issue["due"] == "2026-10-09" and issue["scheduled"].startswith("2026-10-08T09:00:00")


async def test_issues_are_in_the_export(project, db_client: AsyncClient) -> None:
    import io
    import zipfile

    ada, _, url = await project()
    epic = await new(db_client, url, ada.headers, type="epic", title="Scheduled delivery")
    story = await new(db_client, url, ada.headers, type="story", parent=epic["key"], title="Book a slot",
                      description="Acceptance: merchant picks a slot.", labels=["api"])
    await patch(db_client, url, story["key"], ada.headers, status="in_progress", note="Started")
    export = await db_client.get(url.replace("/issues", "/knowledge/export"), headers=ada.headers)
    archive = zipfile.ZipFile(io.BytesIO(export.content))
    text = archive.read(f".pmagent/issues/{story['key']}.md").decode()
    assert text.startswith("---\nkey: KUN-2\ntype: story\ntitle: Book a slot\nstatus: in_progress")
    assert f"parent: {epic['key']}" in text and "Acceptance: merchant picks a slot." in text
    assert "## Log" in text and "updated: Started" in text
    assert f".pmagent/issues/{epic['key']}.md" in archive.namelist()


# -- across projects (My issues, Tasks) ---------------------------------------------------


async def test_issues_across_projects(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    team = await create_team(ada.headers)
    ws = f"/v1/workspaces/{team['id']}"
    await add_member(team["id"], bob.id, Role.MEMBER)

    async def project(key: str) -> tuple[dict, str]:
        res = await db_client.post(f"{ws}/projects", json={"key": key, "name": key.title()}, headers=ada.headers)
        assert res.status_code == 201, res.text
        return res.json(), f"{ws}/projects/{res.json()['id']}/issues"

    kun, kun_url = await project("KUN")
    _, mob_url = await project("MOB")
    sec, sec_url = await project("SEC")
    await db_client.patch(f"{ws}/projects/{sec['id']}", json={"access": "restricted"}, headers=ada.headers)

    late = await new(db_client, kun_url, ada.headers, title="Late", assignee_user_id=bob.id, due="2026-09-30")
    soon = await new(db_client, mob_url, ada.headers, title="Soon", assignee_user_id=bob.id, due="2026-10-07")
    await new(db_client, mob_url, ada.headers, title="Undated", assignee_user_id=bob.id)
    await new(db_client, kun_url, ada.headers, title="Ada's own")
    await new(db_client, sec_url, ada.headers, title="Hidden from Bob")

    mine = (await db_client.get(f"{ws}/issues", params={"assignee": "me"}, headers=bob.headers)).json()
    # Earliest due first, undated last.
    assert [i["title"] for i in mine] == ["Late", "Soon", "Undated"]
    # The restricted project Bob isn't on is left out of everything he lists.
    everything = (await db_client.get(f"{ws}/issues", headers=bob.headers)).json()
    assert len(everything) == 4 and "Hidden from Bob" not in [i["title"] for i in everything]
    assert mine[0]["project_key"] == "KUN" and mine[0]["project_id"] == kun["id"]
    assert mine[0]["key"] == late["key"] and mine[1]["key"] == soon["key"]

    due = await db_client.get(f"{ws}/issues", params={"assignee": "me", "due_before": "2026-10-01"}, headers=bob.headers)
    assert [i["title"] for i in due.json()] == ["Late"]

    # An owner sees every project; reporter and watching filters follow the person.
    reported = (await db_client.get(f"{ws}/issues", params={"reporter": "me"}, headers=ada.headers)).json()
    assert len(reported) == 5
    assert (await db_client.get(f"{ws}/issues", params={"reporter": "me"}, headers=bob.headers)).json() == []
    watched = (await db_client.get(f"{ws}/issues", params={"watching": True}, headers=ada.headers)).json()
    assert len(watched) == 5  # the reporter watches what they create

    bad = await db_client.get(f"{ws}/issues", params={"reporter": "someone"}, headers=ada.headers)
    assert bad.status_code == 422
