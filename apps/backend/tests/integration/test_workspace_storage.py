"""A workspace's storage limit: document originals and task attachments count, an upload that
would pass the limit is refused (413 `storage_full`), usage is summed from the rows."""
import pytest
from httpx import AsyncClient

from dotrix_backend.core.settings import Settings
from dotrix_backend.core.storage import MemoryBlobStorage

MB = 1_000_000
ADMIN = {"email": "admin@example.com", "name": "Admin", "password": "admin secret 123"}


def settings_of(client: AsyncClient) -> Settings:
    return client._transport.app.state.settings  # type: ignore[attr-defined]


def settings_of_env(env: str, **overrides) -> Settings:
    return Settings.model_construct(env=env, **overrides)


@pytest.fixture
def limit(db_client: AsyncClient):
    """Set the deployment's limit (MB) for one test."""
    settings = settings_of(db_client)
    before = settings.workspace_storage_mb

    def _set(mb: int | None) -> None:
        settings.workspace_storage_mb = mb

    yield _set
    settings.workspace_storage_mb = before


@pytest.fixture
def world(db_client: AsyncClient, signup, create_team):
    async def _make(key: str = "KUN", email: str = "ada@example.com"):
        ada = await signup(email=email)
        team = await create_team(ada.headers)
        ws = f"/v1/workspaces/{team['id']}"
        project = (await db_client.post(f"{ws}/projects", json={"key": key, "name": "Kunemi"}, headers=ada.headers)).json()
        base = f"{ws}/projects/{project['id']}"
        await db_client.post(f"{base}/issues", json={"type": "task", "title": "x"}, headers=ada.headers)
        return ada, team, base

    return _make


async def doc(client: AsyncClient, base: str, headers, name: str, size: int):
    return await client.post(f"{base}/documents", files={"file": (name, b"a" * size, "text/plain")}, headers=headers)


async def attach(client: AsyncClient, base: str, headers, size: int, name: str = "log.bin"):
    return await client.post(
        f"{base}/issues/KUN-1/attachments",
        files={"file": (name, b"b" * size, "application/octet-stream")}, headers=headers,
    )


async def storage_of(client: AsyncClient, team: dict, headers) -> dict:
    res = await client.get(f"/v1/workspaces/{team['id']}/storage", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


async def test_usage_is_split_by_kind(db_client: AsyncClient, world, limit) -> None:
    limit(1)
    ada, team, base = await world()
    assert (await doc(db_client, base, ada.headers, "a.txt", 300_000)).status_code == 201
    assert (await attach(db_client, base, ada.headers, 200_000)).status_code == 201
    assert await storage_of(db_client, team, ada.headers) == {
        "used_bytes": 500_000, "limit_bytes": MB, "documents_bytes": 300_000, "attachments_bytes": 200_000,
    }


async def test_an_upload_past_the_limit_is_refused_and_leaves_nothing(
    db_client: AsyncClient, world, limit, storage: MemoryBlobStorage
) -> None:
    limit(1)
    ada, team, base = await world()
    assert (await doc(db_client, base, ada.headers, "a.txt", 700_000)).status_code == 201
    stored = dict(storage.objects)

    refused = await doc(db_client, base, ada.headers, "b.txt", 400_000)
    assert refused.status_code == 413 and refused.json()["type"].endswith("storage_full"), refused.text
    assert "storage is full" in refused.json()["detail"]
    refused = await attach(db_client, base, ada.headers, 400_000)
    assert refused.status_code == 413 and refused.json()["type"].endswith("storage_full")

    assert storage.objects == stored
    assert len((await db_client.get(f"{base}/documents", headers=ada.headers)).json()) == 1
    issue = (await db_client.get(f"{base}/issues/KUN-1", headers=ada.headers)).json()
    assert issue["attachments"] == []
    assert (await storage_of(db_client, team, ada.headers))["used_bytes"] == 700_000


async def test_deleting_makes_room(db_client: AsyncClient, world, limit) -> None:
    limit(1)
    ada, _, base = await world()
    first = (await doc(db_client, base, ada.headers, "a.txt", 700_000)).json()
    assert (await doc(db_client, base, ada.headers, "b.txt", 700_000)).status_code == 413
    assert (await db_client.delete(f"{base}/documents/{first['id']}", headers=ada.headers)).status_code == 204
    assert (await doc(db_client, base, ada.headers, "b.txt", 700_000)).status_code == 201


async def test_duplicate_is_refused_when_it_would_not_fit(db_client: AsyncClient, world, limit) -> None:
    limit(1)
    ada, _, base = await world()
    first = (await doc(db_client, base, ada.headers, "a.txt", 600_000)).json()
    res = await db_client.post(f"{base}/documents/{first['id']}/duplicate", headers=ada.headers)
    assert res.status_code == 413 and res.json()["type"].endswith("storage_full")
    assert len((await db_client.get(f"{base}/documents", headers=ada.headers)).json()) == 1


async def test_a_workspace_limit_overrides_the_setting_both_ways(
    db_client: AsyncClient, db_session, world, limit
) -> None:
    from dotrix_backend.modules.workspaces.models import Workspace

    limit(1)
    ada, team, base = await world()
    workspace = await db_session.get(Workspace, __import__("uuid").UUID(team["id"]))

    async def set_mb(mb: int | None) -> None:
        workspace.storage_limit_mb = mb
        await db_session.commit()

    assert (await doc(db_client, base, ada.headers, "a.txt", 900_000)).status_code == 201
    assert (await doc(db_client, base, ada.headers, "b.txt", 900_000)).status_code == 413
    await set_mb(5)  # higher than the deployment's
    assert (await storage_of(db_client, team, ada.headers))["limit_bytes"] == 5 * MB
    assert (await doc(db_client, base, ada.headers, "b.txt", 900_000)).status_code == 201
    await set_mb(1)  # lower than what it holds: nothing more fits
    assert (await doc(db_client, base, ada.headers, "c.txt", 10_000)).status_code == 413
    await set_mb(0)  # unlimited for this workspace
    assert (await storage_of(db_client, team, ada.headers))["limit_bytes"] is None
    assert (await doc(db_client, base, ada.headers, "c.txt", 900_000)).status_code == 201
    await set_mb(None)  # follows the deployment again
    assert (await storage_of(db_client, team, ada.headers))["limit_bytes"] == MB


async def test_no_limit_refuses_nothing(db_client: AsyncClient, world, limit) -> None:
    limit(0)
    ada, team, base = await world()
    assert (await doc(db_client, base, ada.headers, "a.txt", 3 * MB)).status_code == 201
    assert (await attach(db_client, base, ada.headers, 3 * MB)).status_code == 201
    assert (await storage_of(db_client, team, ada.headers))["limit_bytes"] is None


async def test_the_default_is_unlimited_in_tests_and_a_gigabyte_when_deployed() -> None:
    assert settings_of_env("test").workspace_storage_limit_mb == 0
    assert settings_of_env("development", workspace_storage_mb=50).workspace_storage_limit_mb == 50
    assert settings_of_env("production").workspace_storage_limit_mb == 1024
    assert settings_of_env("production", workspace_storage_mb=0).workspace_storage_limit_mb == 0


async def test_over_the_limit_still_reads_downloads_and_deletes(
    db_client: AsyncClient, world, limit
) -> None:
    limit(0)
    ada, team, base = await world()
    first = (await doc(db_client, base, ada.headers, "a.txt", 800_000)).json()
    limit(1)
    await attach(db_client, base, ada.headers, 100_000)
    limit(0)
    assert (await doc(db_client, base, ada.headers, "b.txt", 900_000)).status_code == 201
    limit(1)  # now 1.8 MB held against a 1 MB limit
    assert (await doc(db_client, base, ada.headers, "c.txt", 1_000)).status_code == 413
    assert (await db_client.get(f"{base}/documents/{first['id']}/original", headers=ada.headers)).status_code == 200
    assert (await storage_of(db_client, team, ada.headers))["used_bytes"] > MB
    assert (await db_client.delete(f"{base}/documents/{first['id']}", headers=ada.headers)).status_code == 204


async def test_moving_a_project_needs_room_in_the_destination(
    db_client: AsyncClient, world, limit, db_session
) -> None:
    from dotrix_backend.modules.workspaces.models import Workspace

    limit(0)
    ada, team, base = await world()
    personal = next(
        w for w in (await db_client.get("/v1/workspaces", headers=ada.headers)).json() if w["kind"] == "personal"
    )
    await doc(db_client, base, ada.headers, "a.txt", 800_000)
    target = await db_session.get(Workspace, __import__("uuid").UUID(personal["id"]))
    target.storage_limit_mb = 1
    await db_session.commit()

    # Something already in the personal workspace leaves no room for 800 KB more.
    other = (
        await db_client.post(f"/v1/workspaces/{personal['id']}/projects", json={"key": "OTH", "name": "O"}, headers=ada.headers)
    ).json()
    obase = f"/v1/workspaces/{personal['id']}/projects/{other['id']}"
    assert (await doc(db_client, obase, ada.headers, "o.txt", 500_000)).status_code == 201
    refused = await db_client.post(f"{base}/move", json={"workspace_id": personal["id"]}, headers=ada.headers)
    assert refused.status_code == 413 and refused.json()["type"].endswith("storage_full"), refused.text
    assert (await db_client.get(base, headers=ada.headers)).status_code == 200  # still where it was

    target.storage_limit_mb = 2
    await db_session.commit()
    moved = await db_client.post(f"{base}/move", json={"workspace_id": personal["id"]}, headers=ada.headers)
    assert moved.status_code == 200, moved.text
    assert (await storage_of(db_client, team, ada.headers))["used_bytes"] == 0
    assert (await storage_of(db_client, personal, ada.headers))["used_bytes"] == 1_300_000


async def test_another_workspaces_uploads_do_not_count(db_client: AsyncClient, world, limit, signup, create_team) -> None:
    limit(1)
    ada, team, base = await world()
    bob, bteam, bbase = await world(key="BOB", email="bob@example.com")
    assert (await doc(db_client, base, ada.headers, "a.txt", 900_000)).status_code == 201
    assert (await doc(db_client, bbase, bob.headers, "b.txt", 900_000)).status_code == 201
    assert (await storage_of(db_client, bteam, bob.headers))["used_bytes"] == 900_000
    # Not a member: the route answers 404 like any other workspace's.
    assert (await db_client.get(f"/v1/workspaces/{team['id']}/storage", headers=bob.headers)).status_code == 404


async def test_the_admin_sets_a_limit_and_it_is_audited(db_client: AsyncClient, world, limit, signup) -> None:
    limit(1)
    ada, team, base = await world()
    await doc(db_client, base, ada.headers, "a.txt", 400_000)
    admin = {"X-Requested-With": "dotrix-admin"}
    res = await db_client.post("/v1/admin/signup", json=ADMIN, headers=admin)
    assert res.status_code == 201, res.text

    listed = (await db_client.get("/v1/admin/observe/workspaces", headers=admin)).json()
    row = next(w for w in listed if w["id"] == team["id"])
    assert row["used_bytes"] == 400_000 and row["storage_limit_mb"] is None and row["effective_limit_bytes"] == MB

    url = "/v1/admin/storage-limit"
    assert (await db_client.put(url, json={"workspace_id": team["id"], "storage_limit_mb": 3}, headers=admin)).status_code == 204
    row = next(w for w in (await db_client.get("/v1/admin/observe/workspaces", headers=admin)).json() if w["id"] == team["id"])
    assert row["storage_limit_mb"] == 3 and row["effective_limit_bytes"] == 3 * MB
    assert (await storage_of(db_client, team, ada.headers))["limit_bytes"] == 3 * MB
    assert (await db_client.put(url, json={"workspace_id": team["id"], "storage_limit_mb": -1}, headers=admin)).status_code == 422

    events = (await db_client.get(f"/v1/workspaces/{team['id']}/audit?action=workspace.storage_limit_updated", headers=ada.headers))
    assert events.status_code == 200, events.text
    details = [e["details"] for e in events.json()]
    assert details and details[0]["from_mb"] is None and details[0]["to_mb"] == 3


async def test_a_member_cannot_use_the_admin_route(db_client: AsyncClient, world) -> None:
    ada, team, _ = await world()
    url = "/v1/admin/storage-limit"
    res = await db_client.put(url, json={"workspace_id": team["id"], "storage_limit_mb": 0}, headers={**ada.headers, "X-Requested-With": "x"})
    assert res.status_code == 401
