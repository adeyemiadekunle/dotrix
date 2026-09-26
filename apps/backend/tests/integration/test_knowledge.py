import io
import uuid
import zipfile

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core.errors import Forbidden
from pmagent_backend.modules.knowledge.service import Actor, KnowledgeService
from pmagent_backend.modules.projects.repository import ProjectRepository
from pmagent_backend.modules.workspaces.models import Role


@pytest.fixture
def make_project(db_client: AsyncClient, create_team):
    async def _make(headers: dict[str, str], key: str = "KUN") -> tuple[str, dict]:
        team = await create_team(headers)
        res = await db_client.post(
            f"/v1/workspaces/{team['id']}/projects", json={"key": key, "name": "Kunemi"}, headers=headers
        )
        assert res.status_code == 201, res.text
        project = res.json()
        return f"/v1/workspaces/{team['id']}/projects/{project['id']}/knowledge", project | {
            "workspace_id": team["id"]
        }

    return _make


# -- read / write / history -----------------------------------------------------------


async def test_write_read_and_history(signup, make_project, db_client: AsyncClient) -> None:
    ada = await signup()
    kb, _ = await make_project(ada.headers)
    url = f"{kb}/files/requirements/product.md"

    res = await db_client.put(
        url, json={"content": "# Product\n\nDrivers.\n", "base_version": 1, "message": "first"},
        headers=ada.headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["version"] == 2 and res.json()["revision"] == 2

    got = (await db_client.get(url, headers=ada.headers)).json()
    assert got["content"] == "# Product\n\nDrivers.\n"

    history = (await db_client.get(f"{url}/versions", headers=ada.headers)).json()
    assert [v["version"] for v in history] == [2, 1]
    assert history[0]["author_type"] == "user" and history[0]["author_id"] == ada.id
    assert history[0]["instructed_by_id"] == ada.id == history[0]["approved_by_id"]
    assert history[0]["message"] == "first"
    assert history[1]["author_type"] == "system"

    diff = (await db_client.get(f"{url}/versions/2/diff", headers=ada.headers)).json()
    assert "-# Product requirements" in diff["diff"] and "+Drivers." in diff["diff"]
    old = (await db_client.get(f"{url}/versions/1", headers=ada.headers)).json()
    assert old["content"] == "# Product requirements\n"


async def test_new_file_and_unchanged_write(signup, make_project, db_client: AsyncClient) -> None:
    ada = await signup()
    kb, _ = await make_project(ada.headers)
    url = f"{kb}/files/research/postcodes.md"
    first = await db_client.put(url, json={"content": "x", "base_version": 0}, headers=ada.headers)
    assert first.status_code == 200 and first.json()["version"] == 1
    same = await db_client.put(url, json={"content": "x"}, headers=ada.headers)
    assert same.json()["version"] == 1 and same.json()["revision"] == first.json()["revision"]


async def test_stale_base_version_conflicts(signup, make_project, db_client: AsyncClient) -> None:
    ada = await signup()
    kb, _ = await make_project(ada.headers)
    url = f"{kb}/files/vision.md"
    await db_client.put(url, json={"content": "one", "base_version": 1}, headers=ada.headers)
    stale = await db_client.put(url, json={"content": "two", "base_version": 1}, headers=ada.headers)
    assert stale.status_code == 409 and stale.json()["type"].endswith("/version_conflict")
    assert (await db_client.get(url, headers=ada.headers)).json()["content"] == "one"


async def test_delete_and_restore(signup, make_project, db_client: AsyncClient) -> None:
    ada = await signup()
    kb, _ = await make_project(ada.headers)
    url = f"{kb}/files/roadmap.md"
    original = (await db_client.get(url, headers=ada.headers)).json()["content"]

    assert (await db_client.delete(url, headers=ada.headers)).status_code == 204
    assert (await db_client.get(url, headers=ada.headers)).status_code == 404
    history = (await db_client.get(f"{url}/versions", headers=ada.headers)).json()
    assert history[0]["deleted"] is True

    restored = await db_client.post(f"{url}/restore", json={"version": 1}, headers=ada.headers)
    assert restored.status_code == 200 and restored.json()["version"] == 3
    assert restored.json()["content"] == original
    cant = await db_client.post(f"{url}/restore", json={"version": 2}, headers=ada.headers)
    assert cant.status_code == 422  # version 2 is the deletion


@pytest.mark.parametrize("path", ["../escape.md", "report.pdf", ".env.md", "a//b.md"])
async def test_invalid_paths_are_rejected(signup, make_project, db_client: AsyncClient, path: str) -> None:
    ada = await signup()
    kb, _ = await make_project(ada.headers)
    res = await db_client.put(f"{kb}/files/{path}", json={"content": "x"}, headers=ada.headers)
    assert res.status_code in (404, 422), path  # 404 only if the router rejects the URL shape
    if res.status_code == 422:
        assert res.json()["type"].endswith(("/invalid_path", "/validation_error"))


async def test_file_size_limit(signup, make_project, db_client: AsyncClient) -> None:
    ada = await signup()
    kb, _ = await make_project(ada.headers)
    res = await db_client.put(
        f"{kb}/files/research/big.md", json={"content": "x" * 1_000_001}, headers=ada.headers
    )
    assert res.status_code == 422 and res.json()["type"].endswith("/file_too_large")


# -- sync and export ------------------------------------------------------------------


async def test_manifest_since_revision(signup, make_project, db_client: AsyncClient) -> None:
    ada = await signup()
    kb, _ = await make_project(ada.headers)
    start = (await db_client.get(kb, headers=ada.headers)).json()["revision"]

    await db_client.put(f"{kb}/files/vision.md", json={"content": "v"}, headers=ada.headers)
    await db_client.delete(f"{kb}/files/roadmap.md", headers=ada.headers)
    changed = (await db_client.get(kb, params={"since_revision": start}, headers=ada.headers)).json()
    assert changed["revision"] == start + 2
    assert {(f["path"], f["deleted"]) for f in changed["files"]} == {
        ("vision.md", False),
        ("roadmap.md", True),
    }
    assert (await db_client.get(kb, params={"since_revision": changed["revision"]}, headers=ada.headers)).json()[
        "files"
    ] == []
    full = (await db_client.get(kb, headers=ada.headers)).json()
    assert "roadmap.md" not in {f["path"] for f in full["files"]}


async def test_export_zip(signup, make_project, db_client: AsyncClient) -> None:
    ada = await signup()
    kb, _ = await make_project(ada.headers)
    await db_client.put(f"{kb}/files/vision.md", json={"content": "Our vision"}, headers=ada.headers)
    res = await db_client.get(f"{kb}/export", headers=ada.headers)
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
    assert 'filename="kun-pmagent.zip"' in res.headers["content-disposition"]
    archive = zipfile.ZipFile(io.BytesIO(res.content))
    names = set(archive.namelist())
    assert {".pmagent/config.yaml", ".pmagent/vision.md", ".pmagent/agent-rules/base.md"} <= names
    assert archive.read(".pmagent/vision.md") == b"Our vision"
    assert b"key: KUN" in archive.read(".pmagent/config.yaml")


# -- who may write --------------------------------------------------------------------


async def test_people_permissions(signup, make_project, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    kb, project = await make_project(ada.headers)
    await add_member(project["workspace_id"], bob.id, Role.MEMBER)

    # Members edit knowledge, but not agent rules, and can't export.
    ok = await db_client.put(f"{kb}/files/vision.md", json={"content": "b"}, headers=bob.headers)
    assert ok.status_code == 200
    rules = await db_client.put(f"{kb}/files/agent-rules/base.md", json={"content": "b"}, headers=bob.headers)
    assert rules.status_code == 403
    assert (await db_client.get(f"{kb}/export", headers=bob.headers)).status_code == 403
    # Owners edit agent rules.
    rules = await db_client.put(f"{kb}/files/agent-rules/base.md", json={"content": "a"}, headers=ada.headers)
    assert rules.status_code == 200


async def test_read_only_api_token_cannot_write(signup, make_project, db_client: AsyncClient) -> None:
    ada = await signup()
    kb, _ = await make_project(ada.headers)
    token = (
        await db_client.post("/v1/me/tokens", json={"name": "ro", "scopes": ["read"]}, headers=ada.headers)
    ).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    assert (await db_client.get(f"{kb}/files/vision.md", headers=auth)).status_code == 200
    assert (await db_client.put(f"{kb}/files/vision.md", json={"content": "x"}, headers=auth)).status_code == 403


async def test_agent_writes_follow_the_folder_matrix(
    signup, make_project, db_client: AsyncClient, db_session: AsyncSession
) -> None:
    ada = await signup()
    kb, created = await make_project(ada.headers)
    project = await ProjectRepository(db_session).get(
        uuid.UUID(created["workspace_id"]), uuid.UUID(created["id"])
    )
    service = KnowledgeService(db_session)
    person = uuid.UUID(ada.id)

    def agent(name: str) -> Actor:
        return Actor.agent_run(name, instructed_by_id=person, approved_by_id=person)

    # The owner writes its folder...
    written = await service.write(project, "requirements/product.md", "# By product", agent("product"))
    assert written.version == 2
    # ...Documentation may tidy it...
    await service.write(project, "requirements/product.md", "# By product.", agent("documentation"))
    # ...but Architecture only proposes, the Reviewer reads, and nobody touches agent-rules.
    for name, path in [
        ("architecture", "requirements/product.md"),
        ("reviewer", "requirements/product.md"),
        ("coding", "architecture/overview.md"),
        ("project-manager", "agent-rules/base.md"),
    ]:
        with pytest.raises(Forbidden):
            await service.write(project, path, "nope", agent(name))
    # No write without an instructing and approving person.
    unapproved = Actor.agent_run("product", instructed_by_id=person, approved_by_id=person)
    unapproved = Actor(unapproved.kind, agent="product", instructed_by_id=person, approved_by_id=None)
    with pytest.raises(Forbidden):
        await service.write(project, "requirements/product.md", "x", unapproved)

    history = (await db_client.get(f"{kb}/files/requirements/product.md/versions", headers=ada.headers)).json()
    assert [(v["author_type"], v["agent"]) for v in history[:2]] == [
        ("agent", "documentation"),
        ("agent", "product"),
    ]
    assert history[0]["instructed_by_id"] == ada.id and history[0]["approved_by_id"] == ada.id
