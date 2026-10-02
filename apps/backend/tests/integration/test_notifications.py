"""Notifications: who hears about changes waiting, checkpoints, findings, and assignments; what
counts as unread; and only projects you can still see."""
import pytest
from httpx import AsyncClient

from pmagent_backend.modules.workspaces.models import Role
from pmagent_engine.testing import tool_call


@pytest.fixture
def world(db_client: AsyncClient, create_team, signup, add_member):
    """Ada owns a team with project KUN; Bob is an admin; Cat and Dan are members."""

    async def _make():
        ada = await signup()
        bob = await signup(email="bob@example.com", name="Bob")
        cat = await signup(email="cat@example.com", name="Cat")
        dan = await signup(email="dan@example.com", name="Dan")
        team = await create_team(ada.headers)
        await add_member(team["id"], bob.id, Role.ADMIN)
        await add_member(team["id"], cat.id, Role.MEMBER)
        await add_member(team["id"], dan.id, Role.MEMBER)
        ws = f"/v1/workspaces/{team['id']}"
        project = (await db_client.post(f"{ws}/projects", json={"key": "KUN", "name": "Kunemi"}, headers=ada.headers)).json()
        return ada, bob, cat, dan, ws, f"{ws}/projects/{project['id']}"

    return _make


async def _notifications(db_client: AsyncClient, ws: str, who, **params) -> list[dict]:
    res = await db_client.get(f"{ws}/notifications", params=params, headers=who.headers)
    assert res.status_code == 200, res.text
    return res.json()


async def _counts(db_client: AsyncClient, ws: str, who) -> dict:
    return (await db_client.get(f"{ws}/notifications/counts", headers=who.headers)).json()


async def test_changes_waiting_notify_whoever_may_approve(world, db_client: AsyncClient, agent_script) -> None:
    ada, bob, cat, dan, ws, base = await world()
    # Members may approve here, but Dan can't see the project once it's restricted to Cat.
    await db_client.patch(ws, json={"member_permissions": ["agents:approve"]}, headers=ada.headers)
    await db_client.patch(base, json={"access": "restricted"}, headers=ada.headers)
    assert (await db_client.put(f"{base}/members/{cat.id}", headers=ada.headers)).status_code in (200, 201)

    agent_script.say(tool_call("write_file", file_path="/pmagent/roadmap.md", content="# Roadmap\n"), "Done.")
    run = (await db_client.post(f"{base}/agent/runs", json={"message": "Plan phase 1"}, headers=cat.headers)).json()
    assert run["status"] == "awaiting_approval"

    for person in (ada, bob, cat):
        [note] = await _notifications(db_client, ws, person)
        assert note["kind"] == "approval" and note["title"] == "Plan phase 1" and note["count"] == 1
        assert note["run_id"] == run["id"] and note["thread_id"] == run["thread_id"]
        assert note["project_key"] == "KUN" and note["actor_agent"] == "project-manager"
        assert not note["read"] and not note["resolved"]
        assert (await _counts(db_client, ws, person))["by_kind"]["approval"] == 1
    assert await _notifications(db_client, ws, dan) == []

    # Reading it doesn't make it any less waiting.
    [note] = await _notifications(db_client, ws, bob)
    read = await db_client.post(f"{ws}/notifications/read", json={"ids": [note["id"]]}, headers=bob.headers)
    assert read.json()["by_kind"]["approval"] == 1

    [approval] = run["approvals"]
    decided = await db_client.post(
        f"{base}/agent/runs/{run['id']}/decisions",
        json={"decisions": [{"approval_id": approval["id"], "decision": "approve"}]},
        headers=ada.headers,
    )
    assert decided.status_code == 200, decided.text
    # Decided for everyone: still listed, resolved, and no longer counted.
    [note] = await _notifications(db_client, ws, ada)
    assert note["resolved"] and not note["read"]
    assert await _counts(db_client, ws, bob) == {
        "unread": 0, "by_kind": {"approval": 0, "checkpoint": 0, "assigned": 0, "finding": 0}
    }


async def test_a_checkpoint_notifies_whoever_asked(world, db_client: AsyncClient, agent_script) -> None:
    ada, _, cat, _, ws, base = await world()
    agent_script.say(tool_call("checkpoint", summary="Eight steps", plan=["Spec it"]), "Done.")
    run = (await db_client.post(f"{base}/agent/runs", json={"message": "Plan the launch"}, headers=cat.headers)).json()
    assert run["approvals"][0]["tool"] == "checkpoint"
    [note] = await _notifications(db_client, ws, cat)
    assert note["kind"] == "checkpoint" and note["run_id"] == run["id"]
    # Nothing to approve, so owners hear nothing.
    assert await _notifications(db_client, ws, ada) == []


async def test_findings_notify_whoever_asked(world, db_client: AsyncClient, agent_script) -> None:
    ada, bob, _, _, ws, base = await world()
    await db_client.post(f"{base}/issues", json={"type": "task", "title": "Retry uploads"}, headers=ada.headers)
    agent_script.say(
        tool_call("submit_result", items=[
            {"severity": "medium", "title": "No retry test", "detail": "Criterion 2"},
            {"severity": "low", "title": "No backoff cap", "detail": "Criterion 3"},
        ]),
        "Send it back.",
    )
    run = (await db_client.post(f"{base}/agent/issues/KUN-1/review", headers=ada.headers)).json()
    assert run["status"] == "completed"
    [note] = await _notifications(db_client, ws, ada)
    assert note["kind"] == "finding" and note["count"] == 2 and note["title"] == "Review KUN-1"
    assert note["actor_agent"] == "reviewer" and note["thread_id"] == run["thread_id"]
    assert await _notifications(db_client, ws, bob) == []


async def test_assignments_and_marking_read(world, db_client: AsyncClient) -> None:
    ada, bob, cat, _, ws, base = await world()
    me = (await db_client.get("/v1/me", headers=ada.headers)).json()
    await db_client.post(f"{base}/issues", json={"title": "Mine", "assignee_user_id": me["id"]}, headers=ada.headers)
    await db_client.post(f"{base}/issues", json={"title": "Ship it", "assignee_user_id": bob.id}, headers=ada.headers)
    await db_client.patch(f"{base}/issues/KUN-1", json={"assignee_user_id": cat.id}, headers=ada.headers)

    # Assigning yourself isn't news.
    assert await _notifications(db_client, ws, ada) == []
    [note] = await _notifications(db_client, ws, bob)
    assert note["kind"] == "assigned" and note["issue_key"] == "KUN-2" and note["title"] == "Ship it"
    assert note["actor_user_id"] == me["id"] and note["actor_agent"] is None
    [cats] = await _notifications(db_client, ws, cat, kind="assigned")
    assert cats["issue_key"] == "KUN-1"

    # Someone else's ids are ignored; your own are marked.
    marked = await db_client.post(f"{ws}/notifications/read", json={"ids": [cats["id"]]}, headers=bob.headers)
    assert marked.status_code == 200 and marked.json()["unread"] == 1
    marked = await db_client.post(f"{ws}/notifications/read", json={"ids": [note["id"]]}, headers=bob.headers)
    assert marked.json()["unread"] == 0
    assert await _notifications(db_client, ws, bob, unread=True) == []
    assert (await _notifications(db_client, ws, bob))[0]["read"]
    bad = await db_client.post(f"{ws}/notifications/read", json={}, headers=bob.headers)
    assert bad.status_code == 422
    everything = await db_client.post(f"{ws}/notifications/read", json={"all": True, "kind": "assigned"}, headers=cat.headers)
    assert everything.json()["unread"] == 0

    # Once Cat can't see the project, its notifications are gone for her.
    await db_client.patch(base, json={"access": "restricted"}, headers=ada.headers)
    assert await _notifications(db_client, ws, cat) == []
