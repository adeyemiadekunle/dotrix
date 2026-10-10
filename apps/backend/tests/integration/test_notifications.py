"""Notifications: who hears about changes waiting, checkpoints, findings, and assignments; what
counts as unread; and only projects you can still see."""
import pytest
from httpx import AsyncClient
from langchain_core.messages import AIMessage

from dotrix_backend.modules.workspaces.models import Role
from dotrix_engine.testing import tool_call


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

    agent_script.say(tool_call("write_file", file_path="/dotrix/roadmap.md", content="# Roadmap\n"), "Done.")
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
        "unread": 0,
        "by_kind": {"approval": 0, "checkpoint": 0, "assigned": 0, "finding": 0, "mention": 0, "decided": 0, "watching": 0, "limit": 0},
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


async def test_mentions_in_comments_and_chat(world, db_client: AsyncClient, agent_script) -> None:
    ada, bob, cat, dan, ws, base = await world()
    # Only owners, admins, and Cat see the project; Dan doesn't.
    await db_client.patch(base, json={"access": "restricted"}, headers=ada.headers)
    assert (await db_client.put(f"{base}/members/{cat.id}", headers=ada.headers)).status_code in (200, 201)
    me = (await db_client.get("/v1/me", headers=ada.headers)).json()
    await db_client.post(f"{base}/issues", json={"title": "Retry uploads"}, headers=ada.headers)

    # Named and able to see it: told. Not named (Cat), can't see it (Dan), or yourself: not.
    body = "Thanks @bob, and @Dan when you're back. @Ada too."
    res = await db_client.post(
        f"{base}/issues/KUN-1/comments",
        json={"body": body, "mentions": [bob.id, cat.id, dan.id, me["id"]]},
        headers=ada.headers,
    )
    assert res.status_code == 201, res.text
    [note] = await _notifications(db_client, ws, bob)
    assert note["kind"] == "mention" and note["issue_key"] == "KUN-1" and note["title"] == "Retry uploads"
    assert note["excerpt"] == body and note["actor_user_id"] == me["id"]
    assert (await _counts(db_client, ws, bob))["by_kind"]["mention"] == 1
    for nobody in (ada, cat, dan):
        assert await _notifications(db_client, ws, nobody) == []

    # "@Bobby" isn't "@Bob".
    await db_client.post(
        f"{base}/issues/KUN-1/comments", json={"body": "Ask @Bobby", "mentions": [bob.id]}, headers=ada.headers
    )
    assert len(await _notifications(db_client, ws, bob)) == 1

    # In chat: the conversation is linked.
    agent_script.say("On it.")
    run = (await db_client.post(
        f"{base}/agent/runs", json={"message": "@Bob can you check the roadmap?", "mentions": [bob.id]},
        headers=cat.headers,
    )).json()
    assert run["message"] == "@Bob can you check the roadmap?"
    latest = (await _notifications(db_client, ws, bob, kind="mention"))[0]
    assert latest["run_id"] == run["id"] and latest["thread_id"] == run["thread_id"]
    assert latest["title"] == run["title"] and latest["actor_user_id"] == cat.id


async def test_turning_kinds_off(world, db_client: AsyncClient, agent_script) -> None:
    ada, bob, _, _, ws, base = await world()
    defaults = (await db_client.get("/v1/me/notification-settings", headers=bob.headers)).json()
    assert defaults == {"mention": True, "assigned": True, "finding": True, "decided": True, "watching": True,
                        "email": "immediately"}
    await db_client.post(f"{base}/issues", json={"title": "Ship it", "assignee_user_id": bob.id}, headers=ada.headers)
    agent_script.say(tool_call("write_file", file_path="/dotrix/roadmap.md", content="# R\n"), "Done.")
    await db_client.post(f"{base}/agent/runs", json={"message": "Plan"}, headers=ada.headers)
    assert {n["kind"] for n in await _notifications(db_client, ws, bob)} == {"assigned", "approval"}

    # Assignments off: they stop showing and counting, earlier ones too; approvals can't be turned off.
    res = await db_client.put(
        "/v1/me/notification-settings", json={"mention": True, "assigned": False, "finding": True}, headers=bob.headers
    )
    assert res.json() == {"mention": True, "assigned": False, "finding": True, "decided": True, "watching": True,
                          "email": "immediately"}
    assert [n["kind"] for n in await _notifications(db_client, ws, bob)] == ["approval"]
    counts = await _counts(db_client, ws, bob)
    assert counts["by_kind"]["assigned"] == 0 and counts["unread"] == 1
    # Only Bob's choice: Ada still sees hers.
    assert (await db_client.get("/v1/me/notification-settings", headers=ada.headers)).json()["assigned"] is True


async def _verify(db_session, *people) -> None:
    from datetime import UTC, datetime

    from sqlalchemy import update

    from dotrix_backend.modules.auth.models import User

    await db_session.execute(update(User).where(User.id.in_([p.id for p in people])).values(email_verified_at=datetime.now(UTC)))
    await db_session.commit()


async def _a_minute_later(db_client: AsyncClient, db_session) -> None:
    """The email job's next tick, once the batching minute has passed."""
    from datetime import timedelta

    from sqlalchemy import update

    from dotrix_backend.modules.notifications.models import Notification

    await db_session.execute(update(Notification).values(created_at=Notification.created_at - timedelta(minutes=2)))
    await db_session.commit()
    await db_client._transport.app.state.jobs.enqueue("email_notifications")  # type: ignore[attr-defined]


async def test_emails_as_it_happens_and_the_decision_back(
    world, db_client: AsyncClient, agent_script, db_session, outbox
) -> None:
    ada, bob, cat, _, ws, base = await world()
    await _verify(db_session, ada, cat)  # Bob's address isn't verified: no email for him
    # Two changes in one turn: they wait together, as one batch.
    agent_script.say(
        AIMessage(content="", tool_calls=[
            {"name": "write_file", "args": {"file_path": "/dotrix/roadmap.md", "content": "# Roadmap\n"},
             "id": "w1", "type": "tool_call"},
            {"name": "write_file", "args": {"file_path": "/dotrix/vision.md", "content": "# Vision\n"},
             "id": "w2", "type": "tool_call"},
        ]),
        "Done.",
    )
    run = (await db_client.post(f"{base}/agent/runs", json={"message": "Plan phase 1"}, headers=cat.headers)).json()
    sent = len(outbox.messages)
    await _a_minute_later(db_client, db_session)
    mine = [m for m in outbox.messages[sent:] if m.to == ada.email]
    assert [m.to for m in outbox.messages[sent:]] == [ada.email]  # one email for the run, to the verified approver
    assert "2 changes wait for your decision: Plan phase 1" in mine[0].subject
    assert "/w/" in mine[0].body and "/approvals?n=" in mine[0].body and "KUN · " in mine[0].body
    await _a_minute_later(db_client, db_session)
    assert len(outbox.messages) == sent + 1  # handled once

    # Ada rejects one with a reason: Cat, who asked, hears what happened and why.
    pending = [a for a in run["approvals"] if a["status"] == "pending"]
    await db_client.post(f"{base}/agent/runs/{run['id']}/decisions", headers=ada.headers, json={"decisions": [
        {"approval_id": pending[0]["id"], "decision": "approve"},
        {"approval_id": pending[1]["id"], "decision": "reject", "reason": "The vision is still being written"},
    ]})
    [decided] = [n for n in await _notifications(db_client, ws, cat) if n["kind"] == "decided"]
    assert decided["title"] == "1 approved, 1 rejected: Plan phase 1" and decided["excerpt"] == "The vision is still being written"
    await _a_minute_later(db_client, db_session)
    [email] = outbox.messages[sent + 1:]
    assert email.to == cat.email and 'Why: "The vision is still being written"' in email.body


async def test_daily_digest_off_and_read(world, db_client: AsyncClient, agent_script, db_session, outbox) -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from dotrix_backend.modules.auth.models import User
    from dotrix_backend.modules.notifications.emails import NotificationEmails
    from dotrix_backend.modules.notifications.models import Notification

    ada, _, cat, _, ws, base = await world()
    await _verify(db_session, ada, cat)
    settings = (await db_client.get("/v1/me/notification-settings", headers=ada.headers)).json()
    assert settings["email"] == "immediately" and settings["decided"] is True
    await db_client.put("/v1/me/notification-settings", json={**settings, "email": "daily"}, headers=ada.headers)
    yesterday = datetime.now(UTC) - timedelta(days=1)
    await db_session.execute(update(User).where(User.id == ada.id).values(digest_sent_at=yesterday))
    await db_session.commit()
    # The email service directly, at times of the test's choosing (the job also sends digests).
    emails = NotificationEmails(db_session, outbox, "https://pm.example")

    async def minute_passes() -> None:
        await db_session.execute(update(Notification).values(created_at=Notification.created_at - timedelta(minutes=2)))
        await db_session.commit()
        await emails.send_due()

    agent_script.say(tool_call("write_file", file_path="/dotrix/roadmap.md", content="# R\n"), "Done.")
    await db_client.post(f"{base}/agent/runs", json={"message": "Plan phase 2"}, headers=cat.headers)
    sent = len(outbox.messages)
    await minute_passes()
    assert len(outbox.messages) == sent  # daily: nothing as it happens

    morning = datetime.now(UTC).replace(hour=8, minute=5) + timedelta(days=1)
    assert await emails.send_digests(morning - timedelta(hours=2)) == 0  # not before 08:00 UTC
    assert await emails.send_digests(morning) == 1
    digest = outbox.messages[-1]
    assert digest.to == ada.email and digest.subject.startswith("Your day in dotrix") and "Plan phase 2" in digest.body
    assert "https://pm.example/w/" in digest.body
    assert await emails.send_digests(morning + timedelta(hours=1)) == 0  # once a day

    # Off: nothing; and what was read before the minute passed isn't sent.
    await db_client.put("/v1/me/notification-settings", json={**settings, "email": "off"}, headers=ada.headers)
    await db_client.post(f"{base}/issues", json={"type": "task", "title": "Ship", "assignee_user_id": cat.id}, headers=ada.headers)
    [note] = [n for n in await _notifications(db_client, ws, cat) if n["kind"] == "assigned"]
    await db_client.post(f"{ws}/notifications/read", json={"ids": [note["id"]]}, headers=cat.headers)
    sent = len(outbox.messages)
    await minute_passes()
    assert len(outbox.messages) == sent


async def test_watchers_hear_about_changes_and_comments(world, db_client: AsyncClient) -> None:
    ada, _, cat, dan, ws, base = await world()
    key = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Export"}, headers=ada.headers)).json()["key"]
    for who in (cat, dan):
        assert (await db_client.put(f"{base}/issues/{key}/watch", headers=who.headers)).status_code == 200

    await db_client.patch(f"{base}/issues/{key}", json={"status": "in_progress", "due": "2026-11-01"}, headers=ada.headers)
    [changed] = await _notifications(db_client, ws, cat)
    assert changed["kind"] == "watching" and changed["issue_key"] == key
    assert changed["title"] == f"{key} Export: moved to in progress; changed the due date"

    # A comment: the excerpt; whoever commented isn't told about their own; someone mentioned
    # hears it as a mention instead.
    await db_client.post(f"{base}/issues/{key}/comments", headers=cat.headers,
                         json={"body": "Blocked on the API, @Dan", "mentions": [dan.id]})
    assert len(await _notifications(db_client, ws, cat)) == 1
    kinds = sorted(n["kind"] for n in await _notifications(db_client, ws, dan))
    assert kinds == ["mention", "watching"]
    # Ada reported it, so she watches it: she hears about the comment, not her own change.
    [comment] = await _notifications(db_client, ws, ada)
    assert comment["title"] == f"{key} Export: a new comment" and comment["excerpt"] == "Blocked on the API, @Dan"

    # Turned off: none shown, and none made into email either.
    await db_client.put("/v1/me/notification-settings", headers=cat.headers, json={
        "mention": True, "assigned": True, "finding": True, "decided": True, "watching": False, "email": "immediately",
    })
    assert await _notifications(db_client, ws, cat) == []
