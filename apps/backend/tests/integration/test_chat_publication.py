"""Human publication shares only selected text; private provenance and retries stay private."""
import uuid

import pytest
from sqlalchemy import update

from dotrix_backend.modules.agents.models import AgentRun, RunStatus
from dotrix_backend.modules.workspaces.models import Role


@pytest.mark.parametrize("destination", ["requirements", "decisions", "research", "task"])
async def test_selected_outcome_is_shared_once_without_the_private_transcript(
    db_client, signup, create_team, add_member, agent_script, destination,
):
    ada = await signup()
    cat = await signup(email="cat@example.com", name="Cat")
    team = await create_team(ada.headers)
    await add_member(team["id"], cat.id, Role.MEMBER)
    ws = f"/v1/workspaces/{team['id']}"
    project = (await db_client.post(f"{ws}/projects", headers=ada.headers, json={"key": "PUB", "name": "Publication"})).json()
    base = f"{ws}/projects/{project['id']}"
    agent_script.say("Private transcript: secret client name. Public agreement: use PostgreSQL.")
    run = (await db_client.post(f"{base}/agent/runs", headers=ada.headers, json={"message": "Private discussion"})).json()
    assert run["status"] == "completed", run
    url = f"{base}/agent/runs/{run['id']}/publications"
    body = {"request_id": str(uuid.uuid4()), "destination": destination, "title": "Use PostgreSQL",
            "content": "Agreed scope: PostgreSQL for relational data. Rationale: transactions.", "acknowledge_shared": True}
    saved = await db_client.post(url, headers=ada.headers, json=body)
    assert saved.status_code == 200, saved.text
    assert (await db_client.post(url, headers=ada.headers, json=body)).json() == saved.json()
    assert (await db_client.post(url, headers=ada.headers, json=body | {"content": "Changed"})).status_code == 409
    assert (await db_client.get(url, headers=ada.headers)).json() == [saved.json()]
    assert (await db_client.get(url, headers=cat.headers)).status_code == 404
    # A colleague's board permissions do not grant access to the source conversation.
    assert (await db_client.post(url, headers=cat.headers, json=body | {"destination": "task"})).status_code == 404
    target = saved.json()["target"]
    if destination == "task":
        shared = (await db_client.get(f"{base}/issues/{target}", headers=cat.headers)).json()
        assert shared["status"] == "todo" and shared["assignee_agent"] is None
        assert shared["description"] == body["content"]
        assert len((await db_client.get(f"{base}/issues", headers=ada.headers)).json()) == 1
    else:
        shared = (await db_client.get(f"{base}/knowledge/files/{target}", headers=cat.headers)).json()
        assert shared["content"] == f"# {body['title']}\n\n{body['content']}\n"
        assert shared["version"] == 1
        assert (await db_client.post(url, headers=cat.headers, json=body)).status_code == 403
        # A later human correction uses normal optimistic versioning, not republication.
        corrected = await db_client.put(f"{base}/knowledge/files/{target}", headers=ada.headers,
                                        json={"content": "Corrected human knowledge", "base_version": 1})
        assert corrected.status_code == 200 and corrected.json()["version"] == 2
        assert (await db_client.post(url, headers=ada.headers, json=body)).json() == saved.json()
        assert (await db_client.get(f"{base}/knowledge/files/{target}", headers=cat.headers)).json()["content"] == "Corrected human knowledge"
    assert run["id"] not in str(shared) and "secret client" not in str(shared)
    assert (await db_client.get(f"{base}/agent/runs/{run['id']}", headers=cat.headers)).status_code == 404


async def test_publication_rechecks_permission_status_acknowledgement_and_project_scope(
    db_client, signup, create_team, agent_script, db_session,
):
    ada = await signup()
    team = await create_team(ada.headers)
    ws = f"/v1/workspaces/{team['id']}"
    projects = [(await db_client.post(f"{ws}/projects", headers=ada.headers, json={"key": key, "name": key})).json()
                for key in ("ONE", "TWO")]
    base = f"{ws}/projects/{projects[0]['id']}"
    agent_script.say("Agreed result")
    run = (await db_client.post(f"{base}/agent/runs", headers=ada.headers, json={"message": "Discuss"})).json()
    body = {"request_id": str(uuid.uuid4()), "destination": "task", "title": "Scope", "content": "Only this", "acknowledge_shared": True}
    url = f"{base}/agent/runs/{run['id']}/publications"
    assert (await db_client.post(url, headers=ada.headers, json=body | {"acknowledge_shared": False})).status_code == 422
    other = url.replace(projects[0]["id"], projects[1]["id"])
    assert (await db_client.post(other, headers=ada.headers, json=body)).status_code == 404
    await db_session.execute(update(AgentRun).where(AgentRun.id == uuid.UUID(run["id"])).values(status=RunStatus.FAILED))
    await db_session.commit()
    assert (await db_client.post(url, headers=ada.headers, json=body)).status_code == 409


async def test_publication_uses_current_destination_rights_even_for_a_saved_retry(
    db_client, signup, create_team, add_member, agent_script, db_session,
):
    from dotrix_backend.modules.workspaces.models import Membership

    owner = await signup()
    editor = await signup(email="editor@example.com", name="Editor")
    team = await create_team(owner.headers)
    await add_member(team["id"], editor.id, Role.ADMIN)
    ws = f"/v1/workspaces/{team['id']}"
    project = (await db_client.post(f"{ws}/projects", headers=owner.headers, json={"key": "PUB", "name": "Publication"})).json()
    base = f"{ws}/projects/{project['id']}"
    agent_script.say("Discussed result")
    run = (await db_client.post(f"{base}/agent/runs", headers=editor.headers, json={"message": "Discuss"})).json()
    url = f"{base}/agent/runs/{run['id']}/publications"
    body = {"request_id": str(uuid.uuid4()), "destination": "decisions", "title": "Agreed choice", "content": "Only the choice", "acknowledge_shared": True}
    assert (await db_client.post(url, headers=editor.headers, json=body)).status_code == 200
    await db_session.execute(update(Membership).where(
        Membership.workspace_id == uuid.UUID(team["id"]), Membership.user_id == uuid.UUID(editor.id),
    ).values(role=Role.MEMBER))
    await db_session.commit()
    assert (await db_client.post(url, headers=editor.headers, json=body)).status_code == 403
    assert (await db_client.post(url, headers=editor.headers, json=body | {"request_id": str(uuid.uuid4())})).status_code == 403
    # A normal member can still publish their own selected outcome as an unassigned task.
    task = await db_client.post(url, headers=editor.headers, json=body | {"destination": "task", "request_id": str(uuid.uuid4())})
    assert task.status_code == 200, task.text


@pytest.fixture
def shared_publication_world(db_client, signup, create_team, agent_script):
    async def make():
        owner = await signup()
        team = await create_team(owner.headers)
        ws = f"/v1/workspaces/{team['id']}"
        project = (await db_client.post(f"{ws}/projects", headers=owner.headers, json={"key": "PUB", "name": "Publication"})).json()
        base = f"{ws}/projects/{project['id']}"
        agent_script.say("Private analysis and agreed replacement")
        run = (await db_client.post(f"{base}/agent/runs", headers=owner.headers, json={"message": "Discuss"})).json()
        old = "# Original choice\n\nHuman rationale, exactly as written.  \n"
        file = (await db_client.put(f"{base}/knowledge/files/decisions/original.md", headers=owner.headers,
                                    json={"content": old, "base_version": 0})).json()
        body = {"request_id": str(uuid.uuid4()), "destination": "decisions", "title": "Revised choice",
                "content": "New rationale and scope", "acknowledge_shared": True,
                "supersedes": {"path": file["path"], "version": file["version"]}}
        return owner, base, run, old, body
    return make


async def test_supersession_preserves_history_and_exposes_shared_graph_links(
    db_client, shared_publication_world, signup, add_member,
):
    owner, base, run, old, body = await shared_publication_world()
    colleague = await signup(email="colleague@example.com", name="Colleague")
    await add_member(base.split("/")[3], colleague.id, Role.MEMBER)
    issue = (await db_client.post(f"{base}/issues", headers=owner.headers, json={"title": "Implementation"})).json()
    body["related_issue"] = issue["key"]
    url = f"{base}/agent/runs/{run['id']}/publications"
    result = await db_client.post(url, headers=owner.headers, json=body)
    assert result.status_code == 200, result.text
    target = result.json()["target"]
    assert (await db_client.post(url, headers=owner.headers, json=body)).json() == result.json()
    original = (await db_client.get(f"{base}/knowledge/files/decisions/original.md", headers=colleague.headers)).json()
    assert original["version"] == 2 and original["content"].startswith(old)
    assert f"Superseded by: /dotrix/{target}" in original["content"]
    history = (await db_client.get(f"{base}/knowledge/files/decisions/original.md/versions/1", headers=colleague.headers)).json()
    assert history["content"] == old
    links = (await db_client.get(f"{base}/graph/neighbors", headers=colleague.headers,
                                 params={"ref": "decisions/original.md"})).json()["links"]
    assert any(link["direction"] == "in" and link["kind"] == "supersedes" and link["node"]["ref"] == target for link in links)
    new = (await db_client.get(f"{base}/knowledge/files/{target}", headers=colleague.headers)).json()["content"]
    assert "Supersedes: /dotrix/decisions/original.md (reviewed version 1)" in new and issue["key"] in new
    assert run["id"] not in new
    conflict = await db_client.post(url, headers=owner.headers, json=body | {"request_id": str(uuid.uuid4())})
    assert conflict.status_code == 409
    assert (await db_client.get(f"{base}/knowledge/files/decisions/original.md", headers=owner.headers)).json()["version"] == 2


async def test_task_can_follow_reviewed_knowledge_but_not_changed_or_missing_context(db_client, shared_publication_world):
    owner, base, run, old, body = await shared_publication_world()
    url = f"{base}/agent/runs/{run['id']}/publications"
    body = body | {"destination": "task", "supersedes": None, "related_document": body["supersedes"]}
    await db_client.put(f"{base}/knowledge/files/decisions/original.md", headers=owner.headers,
                         json={"content": old + "Correction", "base_version": 1})
    assert (await db_client.post(url, headers=owner.headers, json=body)).status_code == 409
    assert (await db_client.get(f"{base}/issues", headers=owner.headers)).json() == []
    body["related_document"]["version"] = 2
    assert (await db_client.post(url, headers=owner.headers, json=body | {"related_issue": "OTHER-1"})).status_code == 404
    saved = await db_client.post(url, headers=owner.headers, json=body)
    assert saved.status_code == 200, saved.text
    links = (await db_client.get(f"{base}/graph/neighbors", headers=owner.headers,
                                 params={"ref": saved.json()["target"]})).json()["links"]
    assert any(link["kind"] == "decided_by" and link["node"]["ref"] == "decisions/original.md" for link in links)
    assert (await db_client.post(url, headers=owner.headers, json=body)).json() == saved.json()
    for path in ("agent-rules/base.md", "decisions/../project.md", "decisions/line\n.md"):
        assert (await db_client.post(url, headers=owner.headers, json=body | {"related_document": {"path": path, "version": 1}})).status_code == 422


async def test_failed_supersession_rolls_back_destination_and_retry_record(db_client, shared_publication_world, monkeypatch, db_session):
    from dotrix_backend.core.errors import Conflict
    from dotrix_backend.modules.knowledge.service import KnowledgeService

    owner, base, run, old, body = await shared_publication_world()
    write = KnowledgeService.write
    async def fail_predecessor(self, project, path, *args, **kwargs):
        if path == "decisions/original.md":
            raise Conflict("Injected failure before predecessor annotation")
        return await write(self, project, path, *args, **kwargs)
    monkeypatch.setattr(KnowledgeService, "write", fail_predecessor)
    result = await db_client.post(f"{base}/agent/runs/{run['id']}/publications", headers=owner.headers, json=body)
    assert result.status_code == 409
    # Production closes the failed request's session. This test uses one shared session.
    await db_session.rollback()
    files = (await db_client.get(f"{base}/knowledge", headers=owner.headers)).json()["files"]
    assert not any(file["path"].startswith("decisions/chat-") for file in files)
    assert (await db_client.get(f"{base}/agent/runs/{run['id']}/publications", headers=owner.headers)).json() == []
    assert (await db_client.get(f"{base}/knowledge/files/decisions/original.md", headers=owner.headers)).json()["content"] == old


async def test_pre_relationship_publication_retries_keep_their_original_digest(db_client, shared_publication_world, db_session):
    import hashlib
    import json

    from dotrix_backend.modules.agents.models import ChatPublication

    owner, base, run, _, fields = await shared_publication_world()
    body = {key: value for key, value in fields.items() if key != "supersedes"}
    url = f"{base}/agent/runs/{run['id']}/publications"
    saved = await db_client.post(url, headers=owner.headers, json=body)
    assert saved.status_code == 200
    # Simulate the exact persisted hash of the previous schema, which had no relationship fields.
    legacy_fields = {key: value for key, value in body.items() if key != "request_id"}
    digest = hashlib.sha256((run["id"] + json.dumps(legacy_fields, separators=(",", ":"), ensure_ascii=False)).encode()).hexdigest()
    await db_session.execute(update(ChatPublication).where(ChatPublication.run_id == uuid.UUID(run["id"])).values(fingerprint=digest))
    await db_session.commit()
    retried = await db_client.post(url, headers=owner.headers, json=body | {"related_document": None, "related_issue": None, "supersedes": None})
    assert retried.status_code == 200 and retried.json() == saved.json()
