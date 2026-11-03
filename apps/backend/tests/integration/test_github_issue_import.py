"""Reviewed imports use real transactions and mocked GitHub HTTP; never open remote issues."""
import copy
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select, update

from dotrix_backend.core.errors import Conflict
from dotrix_backend.modules.auth.models import OAuthAccount
from dotrix_backend.modules.connectors.github_app import get_github_app
from dotrix_backend.modules.connectors.import_models import GitHubImportedIssue
from dotrix_backend.modules.issues.service import IssueService
from dotrix_backend.modules.workspaces.models import Membership, Role


def source(number, **fields):
    return {"id": 1000+number, "number": number, "title": f"Source {number}", "body": "Original scope",
            "state": "open", "state_reason": None, "labels": [{"name": "backend"}], "assignees": [],
            "updated_at": "2026-11-03T00:00:00Z", **fields}


@pytest.fixture
def backlog(db_client, github_world, github):
    async def make():
        owner, member, ws, project, other = await github_world()
        installation = (await db_client.post(f"{ws}/github/installations", headers=owner.headers,
                                             json={"installation_id": 111, "code": "code-1"})).json()
        base = f"{ws}/projects/{project['id']}"
        connected = await db_client.put(f"{base}/repository", headers=owner.headers,
                                         json={"installation_ref": installation["id"], "github_repo_id": 9001})
        assert connected.status_code == 200, connected.text
        sources = [source(1), source(2, state="closed", state_reason="completed"), source(3, pull_request={"url": "pr"})]
        original = github.handle
        def handle(request):
            if request.method == "GET" and request.url.path.startswith("/repos/kunemi/api/issues"):
                if request.url.path.endswith("/issues"):
                    return httpx.Response(200, json=copy.deepcopy(sources), headers={"Link": '<https://api.github.com/repos/kunemi/api/issues?page=2>; rel="next"'})
                number = int(request.url.path.rsplit("/", 1)[-1])
                found = next((item for item in sources if item["number"] == number), None)
                return httpx.Response(200, json=copy.deepcopy(found)) if found else httpx.Response(404)
            return original(request)
        app = db_client._transport.app
        client = app.dependency_overrides[get_github_app]()
        client.transport = httpx.MockTransport(handle)
        app.dependency_overrides[get_github_app] = lambda: client
        return owner, member, base, other, sources, client, github
    return make


async def preview(db_client, base, owner):
    response = await db_client.post(f"{base}/repository/issues/preview", headers=owner.headers, json={})
    assert response.status_code == 200, response.text
    return response.json()


def confirmation(data, ids=None):
    return {"preview_id": data["id"], "issue_ids": ids or [item["source_id"] for item in data["items"] if not item["blocked"]], "acknowledge_shared": True}


async def test_preview_then_import_retry_never_overwrites_human_work(db_client, backlog):
    owner, member, base, _, sources, _, github = await backlog()
    data = await preview(db_client, base, owner)
    assert data["has_more"] and data["skipped_pull_requests"] == 1 and len(data["items"]) == 2
    assert [item["status"] for item in data["items"]] == ["backlog", "done"]
    assert (await db_client.get(f"{base}/issues", headers=owner.headers)).json() == []
    body = confirmation(data)
    url = f"{base}/repository/issues/import"
    result = await db_client.post(url, headers=owner.headers, json=body)
    assert result.status_code == 200, result.text
    assert [item["outcome"] for item in result.json()["items"]] == ["created", "created"]
    assert (await db_client.post(url, headers=owner.headers, json=body)).json() == result.json()
    assert (await db_client.post(url, headers=owner.headers, json=body | {"issue_ids": [1001]})).status_code == 409
    await db_client.patch(f"{base}/issues/KUN-1", headers=owner.headers, json={"title": "Human correction", "status": "todo"})
    sources[0]["title"] = "Later GitHub edit"
    again = await preview(db_client, base, owner)
    assert again["items"][0]["existing_key"] == "KUN-1"
    skipped = await db_client.post(url, headers=owner.headers, json=confirmation(again))
    assert skipped.status_code == 200, skipped.text
    assert all(item["outcome"] == "already_imported" for item in skipped.json()["items"])
    issue = (await db_client.get(f"{base}/issues/KUN-1", headers=member.headers)).json()
    assert issue["title"] == "Human correction" and issue["status"] == "todo"
    assert issue["links"][0]["url"] == "https://github.com/kunemi/api/issues/1"
    assert github.issues == []
    assert any(request.get("permissions", {}).get("issues") == "read" and request["repository_ids"] == [9001] for request in github.token_requests)
    assert not any(request.get("permissions", {}).get("issues") == "write" for request in github.token_requests)


async def test_changed_or_missing_source_aborts_the_whole_batch(db_client, backlog):
    owner, _, base, _, sources, _, _ = await backlog()
    data = await preview(db_client, base, owner)
    sources[1]["body"] = "Changed after review"
    response = await db_client.post(f"{base}/repository/issues/import", headers=owner.headers, json=confirmation(data))
    assert response.status_code == 409, response.text
    assert (await db_client.get(f"{base}/issues", headers=owner.headers)).json() == []
    sources.pop(1)
    assert (await db_client.post(f"{base}/repository/issues/import", headers=owner.headers, json=confirmation(data))).status_code == 404


async def test_unknown_people_and_unsupported_closures_are_visible(db_client, backlog, db_session):
    owner, member, base, _, sources, _, _ = await backlog()
    db_session.add(OAuthAccount(user_id=uuid.UUID(member.id), provider="github", provider_user_id="42", login="cat-gh", created_at=datetime.now(UTC)))
    await db_session.commit()
    sources[:] = [source(1, assignees=[{"id": 42, "login": "cat-gh"}]),
                  source(2, assignees=[{"id": 99, "login": "unknown"}]),
                  source(3, assignees=[{"id": 42, "login": "cat-gh"}, {"id": 99, "login": "other"}]),
                  source(4, state="closed", state_reason="not_planned")]
    data = await preview(db_client, base, owner)
    assert data["items"][0]["assignee_user_id"] == member.id
    assert data["items"][1]["assignee_user_id"] is None and data["items"][1]["warnings"]
    assert data["items"][2]["assignee_user_id"] is None and data["items"][2]["warnings"]
    assert data["items"][3]["blocked"]
    # An assignee losing project access invalidates the mapped preview too.
    await db_session.execute(update(Membership).where(Membership.user_id == uuid.UUID(member.id)).values(role=Role.GUEST))
    await db_session.commit()
    assert (await db_client.post(f"{base}/repository/issues/import", headers=owner.headers, json=confirmation(data, [1001]))).status_code == 409


async def test_foreign_preview_and_revoked_access_cannot_import(db_client, backlog, db_session):
    owner, member, base, other, _, client, github = await backlog()
    data = await preview(db_client, base, owner)
    body = confirmation(data)
    assert (await db_client.post(f"{base}/repository/issues/import", headers=member.headers, json=body)).status_code == 404
    other_base = base.rsplit("/", 1)[0]+"/"+other["id"]
    assert (await db_client.post(f"{other_base}/repository/issues/import", headers=owner.headers, json=body)).status_code == 404
    # The App losing repository access after preview is not a cached grant.
    github.installations[111]["repos"] = []
    assert (await db_client.post(f"{base}/repository/issues/import", headers=owner.headers, json=body)).status_code == 404
    assert (await db_client.get(f"{base}/issues", headers=owner.headers)).json() == []


async def test_failed_insert_rolls_back_and_deleted_tasks_are_not_resurrected(db_client, backlog, monkeypatch, db_session):
    owner, _, base, _, _, _, _ = await backlog()
    data = await preview(db_client, base, owner)
    original = IssueService._insert
    calls = 0
    async def fail_second(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise Conflict("Injected failure")
        return await original(self, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(IssueService, "_insert", fail_second)
        assert (await db_client.post(f"{base}/repository/issues/import", headers=owner.headers, json=confirmation(data))).status_code == 409
        await db_session.rollback()  # production closes the failed request's session
    assert (await db_client.get(f"{base}/issues", headers=owner.headers)).json() == []
    assert not list(await db_session.scalars(select(GitHubImportedIssue)))
    result = await db_client.post(f"{base}/repository/issues/import", headers=owner.headers, json=confirmation(data))
    assert result.status_code == 200, result.text
    assert (await db_client.delete(f"{base}/issues/KUN-1", headers=owner.headers)).status_code == 204
    again = await preview(db_client, base, owner)
    assert again["items"][0]["blocked"] and again["items"][0]["existing_key"] == "KUN-1"
    skipped = await db_client.post(f"{base}/repository/issues/import", headers=owner.headers, json=confirmation(again, [1001]))
    assert skipped.status_code == 200 and skipped.json()["items"][0]["outcome"] == "deleted_task"


@pytest.mark.parametrize("change", ["expire", "suspend", "disconnect"])
async def test_expired_previews_and_changed_connections_do_not_write(db_client, backlog, db_session, change):
    from datetime import timedelta

    from dotrix_backend.modules.connectors.import_models import GitHubImportPreview
    from dotrix_backend.modules.connectors.models import GitHubInstallation

    owner, _, base, _, _, _, _ = await backlog()
    data = await preview(db_client, base, owner)
    if change == "expire":
        await db_session.execute(update(GitHubImportPreview).where(GitHubImportPreview.id == uuid.UUID(data["id"])).values(expires_at=datetime.now(UTC)-timedelta(seconds=1)))
    elif change == "suspend":
        await db_session.execute(update(GitHubInstallation).values(suspended_at=datetime.now(UTC)))
    else:
        await db_client.delete(f"{base}/repository", headers=owner.headers)
    await db_session.commit()
    response = await db_client.post(f"{base}/repository/issues/import", headers=owner.headers, json=confirmation(data))
    assert response.status_code == {"expire": 409, "suspend": 403, "disconnect": 404}[change], response.text
    assert (await db_client.get(f"{base}/issues", headers=owner.headers)).json() == []


async def test_requester_losing_permissions_during_github_read_cannot_commit(db_client, backlog, db_session, monkeypatch):
    from dotrix_backend.modules.issues.models import Issue

    owner, _, base, _, _, client, _ = await backlog()
    data = await preview(db_client, base, owner)
    original = client.read_issue
    changed = False
    async def revoked(*args, **kwargs):
        nonlocal changed
        result = await original(*args, **kwargs)
        if not changed:
            changed = True
            await db_session.execute(update(Membership).where(Membership.user_id == uuid.UUID(owner.id)).values(role=Role.GUEST))
            await db_session.commit()
        return result
    monkeypatch.setattr(client, "read_issue", revoked)
    response = await db_client.post(f"{base}/repository/issues/import", headers=owner.headers, json=confirmation(data))
    assert response.status_code == 403, response.text
    assert not list(await db_session.scalars(select(Issue).where(Issue.project_id == uuid.UUID(base.rsplit("/", 1)[-1]))))


async def test_preview_retention_does_not_lose_deduplication(db_client, backlog, db_session):
    from datetime import timedelta

    from dotrix_backend.modules.connectors.issue_import import cleanup_import_previews

    owner, _, base, _, _, _, _ = await backlog()
    data = await preview(db_client, base, owner)
    response = await db_client.post(f"{base}/repository/issues/import", headers=owner.headers, json=confirmation(data))
    assert response.status_code == 200, response.text
    assert await cleanup_import_previews(db_session, datetime.now(UTC)+timedelta(days=8)) == 1
    await db_session.commit()
    again = await preview(db_client, base, owner)
    assert [item["existing_key"] for item in again["items"]] == ["KUN-1", "KUN-2"]


async def test_project_transfer_preserves_source_identity_but_discards_pending_preview(db_client, backlog, create_team):
    owner, _, base, _, _, _, _ = await backlog()
    data = await preview(db_client, base, owner)
    imported = await db_client.post(f"{base}/repository/issues/import", headers=owner.headers, json=confirmation(data))
    assert imported.status_code == 200, imported.text
    pending = await preview(db_client, base, owner)
    target = await create_team(owner.headers, name="Destination")
    moved = await db_client.post(f"{base}/move", headers=owner.headers, json={"workspace_id": target["id"]})
    assert moved.status_code == 200, moved.text
    new_base = f"/v1/workspaces/{target['id']}/projects/{base.rsplit('/', 1)[-1]}"
    assert (await db_client.post(f"{new_base}/repository/issues/import", headers=owner.headers, json=confirmation(pending))).status_code == 404
    installation = (await db_client.post(f"/v1/workspaces/{target['id']}/github/installations", headers=owner.headers,
                                          json={"installation_id": 111, "code": "code-2"})).json()
    await db_client.put(f"{new_base}/repository", headers=owner.headers,
                         json={"installation_ref": installation["id"], "github_repo_id": 9001})
    new_preview = await preview(db_client, new_base, owner)
    assert [item["existing_key"] for item in new_preview["items"]] == ["KUN-1", "KUN-2"]


async def test_selection_and_visibility_acknowledgement_are_enforced(db_client, backlog):
    owner, _, base, _, _, _, _ = await backlog()
    data = await preview(db_client, base, owner)
    body = confirmation(data)
    url = f"{base}/repository/issues/import"
    assert (await db_client.post(url, headers=owner.headers, json=body | {"acknowledge_shared": False})).status_code == 422
    assert (await db_client.post(url, headers=owner.headers, json=body | {"issue_ids": [999999]})).status_code == 409
    assert (await db_client.get(f"{base}/issues", headers=owner.headers)).json() == []


async def test_removed_manual_link_requires_verification_retry(db_client, backlog, db_session, monkeypatch):
    from dotrix_backend.modules.issues.models import Issue

    owner, _, base, _, _, client, _ = await backlog()
    created = await db_client.post(f"{base}/issues", headers=owner.headers, json={
        "title": "Manually linked", "links": [{"url": "https://github.com/kunemi/api/issues/1"}],
    })
    assert created.status_code == 201, created.text
    data = await preview(db_client, base, owner)
    original = client.repository
    calls = 0

    async def changed(*args, **kwargs):
        nonlocal calls
        result = await original(*args, **kwargs)
        calls += 1
        if calls == 2:
            await db_session.execute(update(Issue).where(Issue.key == "KUN-1").values(links=[]))
            await db_session.commit()
        return result

    monkeypatch.setattr(client, "repository", changed)
    response = await db_client.post(f"{base}/repository/issues/import", headers=owner.headers, json=confirmation(data))
    assert response.status_code == 409, response.text
    assert len((await db_client.get(f"{base}/issues", headers=owner.headers)).json()) == 1
    retry = await db_client.post(f"{base}/repository/issues/import", headers=owner.headers, json=confirmation(data))
    assert retry.status_code == 200, retry.text
    assert len((await db_client.get(f"{base}/issues", headers=owner.headers)).json()) == 3


async def test_import_keeps_history_and_notifications_without_starting_automations(db_client, backlog, db_session, agent_script):
    from dotrix_backend.modules.agents.models import AgentRun
    from dotrix_backend.modules.audit.models import AuditEvent
    from dotrix_backend.modules.automations.models import AutomationEventRow
    from dotrix_backend.modules.issues.models import Issue, IssueEvent, IssueEventKind, IssueWatcher
    from dotrix_backend.modules.notifications.models import Notification, NotificationKind

    owner, member, base, _, sources, _, _ = await backlog()
    project_id = uuid.UUID(base.rsplit("/", 1)[-1])
    db_session.add(OAuthAccount(user_id=uuid.UUID(member.id), provider="github", provider_user_id="42", login="cat-gh", created_at=datetime.now(UTC)))
    await db_session.commit()
    sources[0]["assignees"] = [{"id": 42, "login": "cat-gh"}]
    automation = await db_client.post(f"{base}/automations", headers=owner.headers, json={
        "name": "Triage new tasks", "instructions": "Triage the new issues.", "events": ["issue.created"],
    })
    assert automation.status_code == 201, automation.text
    assert automation.json()["enabled"]
    model = agent_script.say("Triaged the manually created issue.")
    data = await preview(db_client, base, owner)
    imported = await db_client.post(f"{base}/repository/issues/import", headers=owner.headers, json=confirmation(data))
    assert imported.status_code == 200, imported.text
    assert not list(await db_session.scalars(select(AutomationEventRow).where(AutomationEventRow.project_id == project_id)))
    events = list(await db_session.scalars(select(IssueEvent).join(Issue).where(Issue.project_id == project_id)))
    assert len(events) == 2 and all(e.kind == IssueEventKind.CREATED and str(e.author_user_id) == owner.id for e in events)
    audits = list(await db_session.scalars(select(AuditEvent).where(AuditEvent.project_id == project_id, AuditEvent.action == "issue.create")))
    assert len(audits) == 2 and all(str(e.actor_user_id) == owner.id for e in audits)
    assert len(list(await db_session.scalars(select(IssueWatcher).where(IssueWatcher.issue_id.in_([e.issue_id for e in events]))))) == 2
    notices = list(await db_session.scalars(select(Notification).where(Notification.project_id == project_id)))
    assert len(notices) == 1 and notices[0].kind == NotificationKind.ASSIGNED and str(notices[0].user_id) == member.id

    jobs = db_client._transport.app.state.jobs
    await jobs.enqueue("run_automations")
    retry = await db_client.post(f"{base}/repository/issues/import", headers=owner.headers, json=confirmation(data))
    assert retry.json() == imported.json()
    await jobs.enqueue("run_automations")
    assert model.received == []
    assert not list(await db_session.scalars(select(AgentRun).where(AgentRun.project_id == project_id)))

    # Ordinary human creation still emits the event and starts the eligible automation.
    normal = await db_client.post(f"{base}/issues", headers=owner.headers, json={"title": "New work"})
    assert normal.status_code == 201, normal.text
    assert len(list(await db_session.scalars(select(AutomationEventRow).where(AutomationEventRow.project_id == project_id)))) == 1
    await jobs.enqueue("run_automations")
    runs = list(await db_session.scalars(select(AgentRun).where(AgentRun.project_id == project_id)))
    assert len(runs) == 1 and str(runs[0].automation_id) == automation.json()["id"]
    assert len(model.received) == 1
