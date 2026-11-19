"""Readiness is saved, scoped evidence, never a provider probe or an execution gate."""
import uuid
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, update

from dotrix_backend.core.crypto import Secrets
from dotrix_backend.modules.agents.models import AgentRun, RunKind, RunStatus
from dotrix_backend.modules.model_keys.models import UserModelKey
from dotrix_backend.modules.model_keys.service import PersonalKeys
from dotrix_backend.modules.projects.models import Project, ProjectSource
from dotrix_backend.modules.workspaces.models import Role


def checks(data):
    return {row["key"]: row for row in data["checks"]}


async def test_saved_readiness_does_not_count_scaffolding_or_require_integrations(db_client, github_world, agent_script):
    owner, member, ws, project, _ = await github_world()
    base = f"{ws}/projects/{project['id']}"
    model = agent_script.say("This must not be called.")
    response = await db_client.get(f"{base}/readiness", headers=owner.headers)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    data = response.json()
    rows = checks(data)
    assert data["next_action"] == "purpose"
    assert rows["purpose"]["state"] == rows["knowledge"]["state"] == rows["model"]["state"] == "missing"
    assert rows["repository"]["state"] == rows["baseline"]["state"] == "optional"
    assert model.received == []
    # Manual project work stays available without GitHub or a personal key.
    assert (await db_client.post(f"{base}/issues", headers=member.headers, json={"title": "Agree scope"})).status_code == 201
    assert (await db_client.patch(base, headers=owner.headers, json={"description": "Help solo developers ship projects."})).status_code == 200
    assert (await db_client.get(f"{base}/readiness", headers=owner.headers)).json()["next_action"] == "knowledge"
    saved = await db_client.put(f"{base}/knowledge/files/requirements/product.md", headers=owner.headers,
                               json={"content": "# Scope\nHelp developers capture project ideas.", "base_version": 1})
    assert saved.status_code == 200, saved.text
    data = (await db_client.get(f"{base}/readiness", headers=owner.headers)).json()
    assert checks(data)["knowledge"]["state"] == "ready" and data["next_action"] == "tasks"


async def test_readiness_is_scoped_and_explains_restricted_actions(db_client, github_world, signup, add_member, db_session):
    owner, member, ws, project, other = await github_world()
    base = f"{ws}/projects/{project['id']}"
    data = (await db_client.get(f"{base}/readiness", headers=member.headers)).json()
    assert not data["next_allowed"] and data["next_restriction"]
    assert checks(data)["knowledge"]["allowed"] and not checks(data)["implementation"]["allowed"]
    outsider = await signup(email="outside@example.com")
    assert (await db_client.get(f"{base}/readiness", headers=outsider.headers)).status_code == 404
    await add_member(ws.rsplit("/", 1)[-1], outsider.id, Role.GUEST)
    assert (await db_client.get(f"{base}/readiness", headers=outsider.headers)).status_code == 404
    await db_session.execute(update(Project).where(Project.id == uuid.UUID(project["id"])).values(access="restricted"))
    await db_session.commit()
    assert (await db_client.get(f"{base}/readiness", headers=member.headers)).status_code == 404
    assert (await db_client.get(f"{ws}/projects/{other['id']}/readiness", headers=member.headers)).status_code == 200


async def test_personal_model_evidence_requires_current_key_and_same_person_project(db_client, github_world, db_session):
    owner, member, ws, project, other = await github_world()
    app = db_client._transport.app
    app.state.secrets = Secrets(Fernet.generate_key().decode())
    base = f"{ws}/projects/{project['id']}"
    key = "sk-ant-test-" + "x" * 32
    saved = await db_client.put("/v1/me/model-keys/anthropic", headers=owner.headers, json={"api_key": key})
    assert saved.status_code == 200, saved.text
    data = (await db_client.get(f"{base}/readiness", headers=owner.headers)).json()
    assert checks(data)["model"]["state"] == "unverified" and data["model_success_at"] is None
    now = datetime.now(UTC)
    db_session.add(AgentRun(workspace_id=uuid.UUID(ws.rsplit("/", 1)[-1]), project_id=uuid.UUID(project["id"]),
        thread_id=uuid.uuid4(), kind=RunKind.CHAT, status=RunStatus.COMPLETED, requested_by_id=uuid.UUID(owner.id),
        message="Private discussion", reply="Private reply", model=project["model"], input_tokens=20, output_tokens=5,
        model_calls=0, created_at=now, updated_at=now, finished_at=now))
    await db_session.commit()
    assert (await db_client.get(f"{base}/readiness", headers=owner.headers)).json()["model_success_at"] is None
    await db_session.execute(update(AgentRun).where(AgentRun.project_id == uuid.UUID(project["id"])).values(model_calls=1))
    await db_session.commit()
    response = await db_client.get(f"{base}/readiness", headers=owner.headers)
    assert checks(response.json())["model"]["state"] == "ready" and response.json()["model_success_at"]
    assert key not in response.text and "Private discussion" not in response.text and "Private reply" not in response.text
    assert checks((await db_client.get(f"{base}/readiness", headers=member.headers)).json())["model"]["state"] == "missing"
    assert (await db_client.get(f"{ws}/projects/{other['id']}/readiness", headers=owner.headers)).json()["model_success_at"] is None
    keys = PersonalKeys(db_session, app.state.secrets)
    row = await db_session.scalar(select(UserModelKey).where(UserModelKey.user_id == uuid.UUID(owner.id)))
    saved_at = row.credential_saved_at
    await keys.limit_reached(uuid.UUID(owner.id), "anthropic", "Synthetic provider limit")
    assert checks((await db_client.get(f"{base}/readiness", headers=owner.headers)).json())["model"]["state"] == "blocked"
    await keys.limit_cleared(uuid.UUID(owner.id), "anthropic")
    row.updated_at = datetime.now(UTC)  # Metadata can advance after the successful run was saved.
    await db_session.commit()
    assert row.credential_saved_at == saved_at
    recovered = (await db_client.get(f"{base}/readiness", headers=owner.headers)).json()
    assert checks(recovered)["model"]["state"] == "ready" and recovered["model_success_at"] == response.json()["model_success_at"]
    # Replacing a key invalidates successful-call evidence for the previous credential.
    await db_client.put("/v1/me/model-keys/anthropic", headers=owner.headers, json={"api_key": key + "changed"})
    assert (await db_client.get(f"{base}/readiness", headers=owner.headers)).json()["model_success_at"] is None
    row = await db_session.scalar(select(UserModelKey).where(UserModelKey.user_id == uuid.UUID(owner.id)))
    row.limit_reached_at = datetime.now(UTC)
    await db_session.commit()
    assert checks((await db_client.get(f"{base}/readiness", headers=owner.headers)).json())["model"]["state"] == "blocked"


async def test_existing_repository_intention_uses_real_connection_not_saved_url(db_client, github_world, db_session):
    owner, _, ws, project, _ = await github_world()
    base = f"{ws}/projects/{project['id']}"
    await db_session.execute(update(Project).where(Project.id == uuid.UUID(project["id"])).values(
        source=ProjectSource.EXISTING_REPO, description="Improve an existing app", repo_url="https://github.com/acme/app"))
    await db_session.commit()
    data = (await db_client.get(f"{base}/readiness", headers=owner.headers)).json()
    assert checks(data)["repository"]["state"] == "missing" and data["next_action"] == "repository"
    # A saved repository URL alone never claims live access or implementation readiness.
    assert checks(data)["implementation"]["state"] == "missing"


async def test_new_codebase_guidance_keeps_planning_before_connection_and_coding_permissions(db_client, github_world, github, db_session):
    from dotrix_backend.modules.connectors.models import ConnectedRepo

    owner, member, ws, project, _ = await github_world()
    app = db_client._transport.app
    app.state.secrets = Secrets(Fernet.generate_key().decode())
    base = f"{ws}/projects/{project['id']}"
    await db_session.execute(update(Project).where(Project.id == uuid.UUID(project["id"])).values(
        source=ProjectSource.NEW_REPO, description="A booking service for solo consultants"))
    await db_session.commit()
    for person in (owner, member):
        saved = await db_client.put("/v1/me/model-keys/anthropic", headers=person.headers, json={"api_key": "test-personal-key-" + "x" * 30})
        assert saved.status_code == 200
    before = (await db_client.get(f"{base}/readiness", headers=owner.headers)).json()
    assert before["next_action"] == "discuss"  # An editable scope draft, no code or model invocation.
    await db_client.put(f"{base}/knowledge/files/requirements/product.md", headers=owner.headers,
                        json={"content": "# Scope\nAccept one appointment at a time.", "base_version": 1})
    await db_client.post(f"{base}/issues", headers=owner.headers, json={"title": "Booking form", "status": "todo"})
    before = (await db_client.get(f"{base}/readiness", headers=owner.headers)).json()
    assert before["next_action"] == "repository"
    installation = await db_client.post(f"{ws}/github/installations", headers=owner.headers,
                                        json={"installation_id": 111, "code": "code-1"})
    connected = await db_client.put(f"{base}/repository", headers=owner.headers,
                                     json={"installation_ref": installation.json()["id"], "github_repo_id": 9001})
    assert connected.status_code == 200, connected.text
    await db_session.execute(update(ConnectedRepo).where(ConnectedRepo.project_id == uuid.UUID(project["id"])).values(checkout_error=None))
    await db_session.commit()
    data = (await db_client.get(f"{base}/readiness", headers=owner.headers)).json()
    assert data["next_action"] == "plan" and data["next_allowed"]
    assert checks(data)["repository"]["state"] == "unverified"  # Saved configuration never means live admission.
    data = (await db_client.get(f"{base}/readiness", headers=member.headers)).json()
    assert data["next_action"] == "tasks" and not checks(data)["implementation"]["allowed"]
    runs = await db_session.scalars(select(AgentRun).where(AgentRun.project_id == uuid.UUID(project["id"])))
    assert not list(runs)


@pytest.mark.parametrize(("path", "base_version"), [("vision.md", 1), ("docs/normalized/scope.md", 0)])
async def test_root_and_uploaded_knowledge_counts_without_counting_renamed_scaffolds(db_client, github_world, path, base_version):
    owner, _, ws, project, _ = await github_world()
    base = f"{ws}/projects/{project['id']}"
    changed = await db_client.patch(base, headers=owner.headers, json={"name": "Changed name", "description": "A useful project goal"})
    assert changed.status_code == 200
    initial = (await db_client.get(f"{base}/readiness", headers=owner.headers)).json()
    assert checks(initial)["knowledge"]["state"] == "missing"
    saved = await db_client.put(f"{base}/knowledge/files/{path}", headers=owner.headers,
                                json={"content": "# Scope\nSupport appointment bookings for consultants.", "base_version": base_version})
    assert saved.status_code in (200, 201), saved.text
    data = (await db_client.get(f"{base}/readiness", headers=owner.headers)).json()
    assert checks(data)["knowledge"]["state"] == "ready" and data["next_action"] == "tasks"
    assert (await db_client.delete(f"{base}/knowledge/files/{path}", headers=owner.headers)).status_code == 204
    data = (await db_client.get(f"{base}/readiness", headers=owner.headers)).json()
    assert checks(data)["knowledge"]["state"] == "missing"


async def test_provider_qualified_project_model_outside_catalogue_is_available(db_client, github_world, db_session):
    owner, _, ws, project, _ = await github_world()
    db_client._transport.app.state.secrets = Secrets(Fernet.generate_key().decode())
    base = f"{ws}/projects/{project['id']}"
    model = "anthropic:custom-supported-model"
    changed = await db_client.patch(base, headers=owner.headers, json={"model": model})
    assert changed.status_code == 200, changed.text
    saved = await db_client.put("/v1/me/model-keys/anthropic", headers=owner.headers,
                                json={"api_key": "synthetic-personal-key-" + "x" * 30})
    assert saved.status_code == 200
    data = (await db_client.get(f"{base}/readiness", headers=owner.headers)).json()
    assert checks(data)["model"]["state"] == "unverified" and model in checks(data)["model"]["detail"]
