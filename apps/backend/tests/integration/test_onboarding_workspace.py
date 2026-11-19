"""The optional first workspace choice is private, durable and never a conversion."""
import asyncio
import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from dotrix_backend.modules.auth.models import User
from dotrix_backend.modules.projects.models import Project
from dotrix_backend.modules.workspaces.models import Workspace, WorkspaceKind
from dotrix_backend.modules.workspaces.schemas import FirstWorkspaceChoice
from dotrix_backend.modules.workspaces.service import WorkspaceService

URL = "/v1/me/onboarding-workspace"


async def test_skip_reuses_personal_and_persists_without_creating_projects(db_client, signup, db_session):
    person = await signup()
    before = (await db_client.get("/v1/workspaces", headers=person.headers)).json()
    assert (await db_client.get("/v1/me", headers=person.headers)).json()["onboarding_workspace_id"] is None
    skipped = await db_client.post(URL, headers=person.headers, json={})
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["id"] == before[0]["id"] and skipped.json()["kind"] == "personal"
    assert (await db_client.post(URL, headers=person.headers, json={})).json()["id"] == before[0]["id"]
    assert (await db_client.get("/v1/me", headers=person.headers)).json()["onboarding_workspace_id"] == before[0]["id"]
    assert len((await db_client.get("/v1/workspaces", headers=person.headers)).json()) == 1
    assert not list(await db_session.scalars(select(Project)))


async def test_organisation_choice_is_owned_separate_and_retry_safe(db_client, signup):
    person = await signup()
    personal = (await db_client.get("/v1/workspaces", headers=person.headers)).json()[0]
    body = {"kind": "organization", "name": "  Studio team  "}
    chosen = await db_client.post(URL, headers=person.headers, json=body)
    assert chosen.status_code == 200, chosen.text
    org = chosen.json()
    assert org["kind"] == "organization" and org["role"] == "owner" and org["name"] == "Studio team"
    assert org["id"] != personal["id"]
    assert (await db_client.post(URL, headers=person.headers, json=body)).json()["id"] == org["id"]
    listed = (await db_client.get("/v1/workspaces", headers=person.headers)).json()
    assert len(listed) == 2 and next(w for w in listed if w["id"] == personal["id"])["kind"] == "personal"
    assert (await db_client.get("/v1/me", headers=person.headers)).json()["onboarding_workspace_id"] == org["id"]
    assert (await db_client.post(URL, headers=person.headers, json={"kind": "organization", "name": "Other"})).status_code == 409
    assert (await db_client.post(URL, headers=person.headers, json={"kind": "personal"})).status_code == 409
    assert len((await db_client.get("/v1/workspaces", headers=person.headers)).json()) == 2


@pytest.mark.parametrize("body", [
    {"kind": "organization"}, {"kind": "organization", "name": "  "},
    {"kind": "personal", "name": "Unexpected team"}, {"kind": "other"},
    {"kind": "organization", "name": "Team", "workspace_id": str(uuid.uuid4())},
])
async def test_invalid_or_foreign_workspace_choices_do_not_create_teams(db_client, signup, body):
    person = await signup()
    assert (await db_client.post(URL, headers=person.headers, json=body)).status_code == 422
    assert len((await db_client.get("/v1/workspaces", headers=person.headers)).json()) == 1
    assert (await db_client.get("/v1/me", headers=person.headers)).json()["onboarding_workspace_id"] is None


async def test_choice_belongs_to_current_user_and_requires_authentication(db_client, signup):
    owner = await signup()
    other = await signup(email="other@example.com")
    assert (await db_client.post(URL, json={})).status_code == 401
    selected = await db_client.post(URL, headers=owner.headers, json={"kind": "organization", "name": "Private founder"})
    assert selected.status_code == 200
    assert (await db_client.get("/v1/me", headers=other.headers)).json()["onboarding_workspace_id"] is None
    own = (await db_client.post(URL, headers=other.headers, json={})).json()
    assert own["kind"] == "personal" and own["id"] != selected.json()["id"]


async def test_concurrent_registration_retries_create_only_one_organisation(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    async with factory() as session:
        user = User(id=user_id, email=f"concurrent-{user_id}@example.test", display_name="Founder")
        session.add(user)
        await session.flush()
        await WorkspaceService(session).create_personal(user)
        await session.commit()
    try:
        async def choose():
            async with factory() as session:
                user = await session.get(User, user_id)
                return await WorkspaceService(session).choose_first(user, FirstWorkspaceChoice(kind="organization", name="Concurrent team"))
        first, second = await asyncio.gather(choose(), choose())
        assert first.id == second.id
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(Workspace).where(
                Workspace.created_by_id == user_id, Workspace.kind == WorkspaceKind.ORGANIZATION,
            )) == 1
    finally:
        async with factory() as session:
            await session.execute(delete(Workspace).where(Workspace.created_by_id == user_id))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
