from datetime import date

import pytest
from httpx import AsyncClient

from dotrix_backend.modules.workspaces.models import Role


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


async def test_backlog_and_no_priority(project, db_client: AsyncClient) -> None:
    ada, _, url = await project()
    idea = await new(db_client, url, ada.headers, title="Someday", status="backlog", priority="none")
    assert (idea["status"], idea["priority"], idea["ready"]) == ("backlog", "none", False)  # not planned yet
    urgent = await new(db_client, url, ada.headers, title="Now", priority="urgent")
    # No priority sorts after every priority; a backlog issue is never next.
    assert (await db_client.get(f"{url}/next", headers=ada.headers)).json()["key"] == urgent["key"]
    by_priority = [i["key"] for i in (await db_client.get(url, params={"order": "priority"}, headers=ada.headers)).json()]
    assert by_priority == [urgent["key"], idea["key"]]


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
    assert list(columns) == ["backlog", "todo", "in_progress", "blocked", "review", "done"]
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
    text = archive.read(f".dotrix/issues/{story['key']}.md").decode()
    assert text.startswith("---\nkey: KUN-2\ntype: story\ntitle: Book a slot\nstatus: in_progress")
    assert f"parent: {epic['key']}" in text and "Acceptance: merchant picks a slot." in text
    assert "## Log" in text and "updated: Started" in text
    assert f".dotrix/issues/{epic['key']}.md" in archive.namelist()


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


# -- checklists, repeats, attachments, stars ----------------------------------------------


async def test_a_checklist_is_kept_in_order_and_logged(project, db_client: AsyncClient) -> None:
    ada, _, url = await project()
    made = await new(db_client, url, ada.headers, checklist=[{"id": "a", "title": "Draft"}, {"id": "b", "title": "Review"}])
    assert [c["title"] for c in made["checklist"]] == ["Draft", "Review"]
    assert made["checklist"][0]["done"] is False

    res = await patch(db_client, url, made["key"], ada.headers, checklist=[
        {"id": "b", "title": "Review", "done": False}, {"id": "a", "title": "Draft", "done": True},
    ])
    assert res.status_code == 200, res.text
    assert [(c["id"], c["done"]) for c in res.json()["checklist"]] == [("b", False), ("a", True)]
    assert any("checklist" in event["changes"] for event in res.json()["log"])


async def test_a_repeating_issue_comes_back_when_finished(project, db_client: AsyncClient) -> None:
    ada, _, url = await project()
    made = await new(
        db_client, url, ada.headers, title="Water the plants", due="2026-10-10", recurrence="weekly",
        checklist=[{"id": "p", "title": "Ferns", "done": True}],
    )
    done = await patch(db_client, url, made["key"], ada.headers, status="done")
    assert done.status_code == 200, done.text

    issues = (await db_client.get(url, headers=ada.headers)).json()
    again = [i for i in issues if i["title"] == "Water the plants" and i["key"] != made["key"]]
    assert len(again) == 1
    assert done.json()["repeated_as"] == again[0]["key"]
    assert again[0]["due"] == "2026-10-17"
    assert again[0]["status"] == "todo"
    detail = (await db_client.get(f"{url}/{again[0]['key']}", headers=ada.headers)).json()
    assert detail["recurrence"] == "weekly"
    assert detail["checklist"] == [{"id": "p", "title": "Ferns", "done": False, "due": None, "assignee_user_id": None}]

    # Reopened and finished again, it doesn't come back twice.
    await patch(db_client, url, made["key"], ada.headers, status="todo")
    await patch(db_client, url, made["key"], ada.headers, status="done")
    titles = [i["title"] for i in (await db_client.get(url, headers=ada.headers)).json()]
    assert titles.count("Water the plants") == 2


async def test_stopping_a_repeat_stops_the_next_one(project, db_client: AsyncClient) -> None:
    ada, _, url = await project()
    made = await new(db_client, url, ada.headers, title="Pay rent", due="2026-10-01", recurrence="monthly")
    await patch(db_client, url, made["key"], ada.headers, recurrence=None)
    await patch(db_client, url, made["key"], ada.headers, status="done")
    titles = [i["title"] for i in (await db_client.get(url, headers=ada.headers)).json()]
    assert titles.count("Pay rent") == 1


def test_next_due_keeps_the_day_and_clamps_to_short_months() -> None:
    from dotrix_backend.modules.issues.models import Recurrence
    from dotrix_backend.modules.issues.service import next_due

    assert next_due(date(2026, 1, 31), Recurrence.MONTHLY) == date(2026, 2, 28)
    assert next_due(date(2026, 12, 15), Recurrence.MONTHLY) == date(2027, 1, 15)
    assert next_due(date(2026, 2, 3), Recurrence.DAILY) == date(2026, 2, 4)
    assert next_due(date(2026, 2, 3), Recurrence.BIWEEKLY) == date(2026, 2, 17)


async def test_any_file_attaches_to_an_issue_and_comes_back(project, db_client: AsyncClient, storage) -> None:
    ada, _, url = await project()
    made = await new(db_client, url, ada.headers)
    png = b"\x89PNG\r\n\x1a\nnot really"
    added = await db_client.post(
        f"{url}/{made['key']}/attachments", files={"file": ("screenshot.png", png, "image/png")}, headers=ada.headers
    )
    assert added.status_code == 201, added.text
    [attachment] = added.json()["attachments"]
    assert (attachment["filename"], attachment["content_type"], attachment["size"]) == ("screenshot.png", "image/png", len(png))
    assert attachment["uploaded_by_id"] == ada.id
    assert any("attachments" in event["changes"] for event in added.json()["log"])
    listed = (await db_client.get(url, headers=ada.headers)).json()
    assert next(i for i in listed if i["key"] == made["key"])["attachment_count"] == 1

    got = await db_client.get(f"{url}/{made['key']}/attachments/{attachment['id']}", headers=ada.headers)
    assert got.status_code == 200 and got.content == png
    assert got.headers["x-content-type-options"] == "nosniff"

    gone = await db_client.delete(f"{url}/{made['key']}/attachments/{attachment['id']}", headers=ada.headers)
    assert gone.status_code == 200, gone.text
    assert gone.json()["attachments"] == []
    assert storage.objects == {}  # the file itself is deleted
    missing = await db_client.get(f"{url}/{made['key']}/attachments/{attachment['id']}", headers=ada.headers)
    assert missing.status_code == 404


async def test_an_attachment_is_found_only_under_its_issue(project, db_client: AsyncClient) -> None:
    ada, _, url = await project()
    first = await new(db_client, url, ada.headers, title="First")
    second = await new(db_client, url, ada.headers, title="Second")
    added = await db_client.post(
        f"{url}/{first['key']}/attachments", files={"file": ("log.txt", b"boom", "text/plain")}, headers=ada.headers
    )
    attachment_id = added.json()["attachments"][0]["id"]
    elsewhere = await db_client.get(f"{url}/{second['key']}/attachments/{attachment_id}", headers=ada.headers)
    assert elsewhere.status_code == 404
    empty = await db_client.post(
        f"{url}/{first['key']}/attachments", files={"file": ("empty.txt", b"", "text/plain")}, headers=ada.headers
    )
    assert empty.status_code == 422


async def test_a_checklist_item_is_assigned_only_to_someone_who_sees_the_project(
    project, db_client: AsyncClient, signup
) -> None:
    ada, _, url = await project()
    stranger = await signup(email="stranger@example.com", name="Stranger")
    refused = await db_client.post(url, json={"title": "x", "checklist": [
        {"id": "a", "title": "Step", "assignee_user_id": stranger.id},
    ]}, headers=ada.headers)
    assert refused.status_code == 422
    twice = await db_client.post(url, json={"title": "x", "checklist": [
        {"id": "a", "title": "One"}, {"id": "a", "title": "Two"},
    ]}, headers=ada.headers)
    assert twice.status_code == 422


async def test_starring_is_for_you_alone(project, db_client: AsyncClient, signup, add_member) -> None:
    ada, team, url = await project()
    made = await new(db_client, url, ada.headers, title="Keep an eye on this")
    grace = await signup(email="grace-star@example.com", name="Grace")
    await add_member(team["id"], grace.id, Role.MEMBER)

    assert (await db_client.put(f"{url}/{made['key']}/star", headers=ada.headers)).status_code == 204
    assert (await db_client.put(f"{url}/{made['key']}/star", headers=ada.headers)).status_code == 204  # idempotent
    mine = (await db_client.get(f"/v1/workspaces/{team['id']}/issues?starred=true", headers=ada.headers)).json()
    assert [i["key"] for i in mine] == [made["key"]]
    theirs = (await db_client.get(f"/v1/workspaces/{team['id']}/issues?starred=true", headers=grace.headers)).json()
    assert theirs == []

    assert (await db_client.delete(f"{url}/{made['key']}/star", headers=ada.headers)).status_code == 204
    assert (await db_client.get(f"/v1/workspaces/{team['id']}/issues?starred=true", headers=ada.headers)).json() == []


# -- archive, delete, move, comments ------------------------------------------------------


async def test_an_archived_issue_leaves_the_board_and_lists(project, db_client: AsyncClient) -> None:
    ada, team, url = await project()
    made = await new(db_client, url, ada.headers, title="Old idea")
    res = await patch(db_client, url, made["key"], ada.headers, archived=True)
    assert res.status_code == 200 and res.json()["archived_at"] is not None

    assert [i["key"] for i in (await db_client.get(url, headers=ada.headers)).json()] == []
    board = (await db_client.get(f"{url}/board", headers=ada.headers)).json()
    assert all(not col["issues"] for col in board["columns"])
    ws = f"/v1/workspaces/{team['id']}/issues"
    assert [i["key"] for i in (await db_client.get(f"{ws}?archived=only", headers=ada.headers)).json()] == [made["key"]]
    assert [i["key"] for i in (await db_client.get(f"{ws}?archived=include", headers=ada.headers)).json()] == [made["key"]]

    await patch(db_client, url, made["key"], ada.headers, archived=False)
    assert [i["key"] for i in (await db_client.get(url, headers=ada.headers)).json()] == [made["key"]]


async def test_deleting_an_issue(project, db_client: AsyncClient, signup, add_member, storage) -> None:
    ada, team, url = await project()
    grace = await signup(email="grace-del@example.com", name="Grace")
    await add_member(team["id"], grace.id, Role.MEMBER)
    epic = await new(db_client, url, ada.headers, type="epic", title="Epic")
    child = await new(db_client, url, ada.headers, title="Child", parent=epic["key"])
    await db_client.post(f"{url}/{child['key']}/attachments", files={"file": ("a.txt", b"a", "text/plain")}, headers=ada.headers)
    hers = await new(db_client, url, grace.headers, title="Grace's")

    assert (await db_client.delete(f"{url}/{epic['key']}", headers=ada.headers)).status_code == 409  # has a child
    assert (await db_client.delete(f"{url}/{child['key']}", headers=grace.headers)).status_code == 403  # not hers
    assert (await db_client.delete(f"{url}/{hers['key']}", headers=grace.headers)).status_code == 204  # she reported it
    assert (await db_client.delete(f"{url}/{child['key']}", headers=ada.headers)).status_code == 204
    assert (await db_client.get(f"{url}/{child['key']}", headers=ada.headers)).status_code == 404
    assert storage.objects == {}
    assert (await db_client.delete(f"{url}/{epic['key']}", headers=ada.headers)).status_code == 204


async def test_moving_an_issue_creates_it_there_with_its_history(project, db_client: AsyncClient) -> None:
    ada, team, url = await project()
    other = (
        await db_client.post(f"/v1/workspaces/{team['id']}/projects", json={"key": "OPS", "name": "Ops"}, headers=ada.headers)
    ).json()
    other_url = f"/v1/workspaces/{team['id']}/projects/{other['id']}/issues"
    blocker = await new(db_client, url, ada.headers, title="Blocker")
    made = await new(
        db_client, url, ada.headers, title="Move me", priority="high", labels=["infra"], depends_on=[blocker["key"]],
        checklist=[{"id": "a", "title": "Step"}],
    )
    await db_client.post(f"{url}/{made['key']}/comments", json={"body": "Keep this"}, headers=ada.headers)
    await db_client.put(f"{url}/{made['key']}/star", headers=ada.headers)
    await db_client.post(
        f"{url}/{made['key']}/attachments", files={"file": ("plan.txt", b"plan", "text/plain")}, headers=ada.headers
    )

    moved = await db_client.post(f"{url}/{made['key']}/move", json={"project_id": other["id"]}, headers=ada.headers)
    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert body["key"] == "OPS-1" and body["title"] == "Move me" and body["priority"] == "high"
    assert body["labels"] == ["infra"] and body["checklist"][0]["title"] == "Step"
    assert body["depends_on"] == []  # dependencies belong to the old project
    assert any(e["kind"] == "commented" and e["body"] == "Keep this" for e in body["log"])
    assert [a["filename"] for a in body["attachments"]] == ["plan.txt"]
    assert any(e["changes"].get("key") == [made["key"], "OPS-1"] for e in body["log"])
    assert (await db_client.get(f"{url}/{made['key']}", headers=ada.headers)).status_code == 404
    starred = (await db_client.get(f"/v1/workspaces/{team['id']}/issues?starred=true", headers=ada.headers)).json()
    assert [i["key"] for i in starred] == ["OPS-1"]
    download = await db_client.get(f"{other_url}/OPS-1/attachments/{body['attachments'][0]['id']}", headers=ada.headers)
    assert download.content == b"plan"

    same = await db_client.post(f"{other_url}/OPS-1/move", json={"project_id": other["id"]}, headers=ada.headers)
    assert same.status_code == 422


async def test_comments_can_be_edited_deleted_and_reacted_to(project, db_client: AsyncClient, signup, add_member) -> None:
    ada, team, url = await project()
    grace = await signup(email="grace-c@example.com", name="Grace")
    await add_member(team["id"], grace.id, Role.MEMBER)
    made = await new(db_client, url, ada.headers)
    posted = (await db_client.post(f"{url}/{made['key']}/comments", json={"body": "First draft"}, headers=grace.headers)).json()
    comment = next(e for e in posted["log"] if e["kind"] == "commented")
    curl = f"{url}/{made['key']}/comments/{comment['id']}"

    assert (await db_client.patch(curl, json={"body": "Not mine"}, headers=ada.headers)).status_code == 403
    edited = await db_client.patch(curl, json={"body": "Second draft"}, headers=grace.headers)
    assert edited.status_code == 200
    after = next(e for e in edited.json()["log"] if e["id"] == comment["id"])
    assert after["body"] == "Second draft" and after["edited_at"] is not None

    await db_client.put(f"{curl}/reactions/\N{THUMBS UP SIGN}", headers=ada.headers)
    await db_client.put(f"{curl}/reactions/\N{THUMBS UP SIGN}", headers=ada.headers)  # once each
    liked = (await db_client.put(f"{curl}/reactions/\N{THUMBS UP SIGN}", headers=grace.headers)).json()
    assert next(e for e in liked["log"] if e["id"] == comment["id"])["reactions"] == {"\N{THUMBS UP SIGN}": [ada.id, grace.id]}
    unliked = (await db_client.delete(f"{curl}/reactions/\N{THUMBS UP SIGN}", headers=ada.headers)).json()
    assert next(e for e in unliked["log"] if e["id"] == comment["id"])["reactions"] == {"\N{THUMBS UP SIGN}": [grace.id]}

    # Owners and admins may delete anyone's comment.
    gone = await db_client.delete(curl, headers=ada.headers)
    assert gone.status_code == 200
    assert not any(e["id"] == comment["id"] for e in gone.json()["log"])
