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
