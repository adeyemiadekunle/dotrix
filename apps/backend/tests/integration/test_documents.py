import hashlib
import io

import pytest
from httpx import AsyncClient
from openpyxl import Workbook

from pmagent_backend.core.storage import MemoryBlobStorage, get_storage
from pmagent_backend.modules.workspaces.models import Role


def xlsx_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["Hub", "State"])
    ws.append(["Ikeja", "Lagos"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


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
        base = f"/v1/workspaces/{team['id']}/projects/{created['id']}"
        return ada, team, base

    return _make


async def upload(client: AsyncClient, base: str, headers, name: str, data: bytes, ctype: str = "text/plain"):
    return await client.post(f"{base}/documents", files={"file": (name, data, ctype)}, headers=headers)


async def test_upload_converts_and_keeps_original(
    project, db_client: AsyncClient, storage: MemoryBlobStorage
) -> None:
    ada, _, base = await project()
    res = await upload(db_client, base, ada.headers, "Hub List.xlsx", xlsx_bytes(), "application/whatever")
    assert res.status_code == 201, res.text
    doc = res.json()
    assert doc["knowledge_path"] == "docs/normalized/hub-list.md" and doc["knowledge_version"] == 1
    # Stored type comes from the extension, not the client's header.
    assert doc["content_type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert len(storage.objects) == 1

    md = (await db_client.get(f"{base}/knowledge/files/{doc['knowledge_path']}", headers=ada.headers)).json()
    assert "Ikeja" in md["content"] and "Imported from `Hub List.xlsx`" in md["content"]
    history = (
        await db_client.get(f"{base}/knowledge/files/{doc['knowledge_path']}/versions", headers=ada.headers)
    ).json()
    assert history[0]["author_id"] == ada.id and history[0]["message"] == "Imported Hub List.xlsx"

    original = await db_client.get(f"{base}/documents/{doc['id']}/original", headers=ada.headers)
    assert original.status_code == 200
    assert hashlib.sha256(original.content).hexdigest() == doc["sha256"]  # byte-for-byte
    assert "attachment" in original.headers["content-disposition"]
    assert original.headers["x-content-type-options"] == "nosniff"

    listed = (await db_client.get(f"{base}/documents", headers=ada.headers)).json()
    assert [d["filename"] for d in listed] == ["Hub List.xlsx"]


async def test_reupload_adds_a_new_version(project, db_client: AsyncClient) -> None:
    ada, _, base = await project()
    first = (await upload(db_client, base, ada.headers, "notes.md", b"# v1")).json()
    second = (await upload(db_client, base, ada.headers, "notes.md", b"# v2")).json()
    assert first["knowledge_path"] == second["knowledge_path"] == "docs/normalized/notes.md"
    assert (first["knowledge_version"], second["knowledge_version"]) == (1, 2)
    assert len((await db_client.get(f"{base}/documents", headers=ada.headers)).json()) == 2


async def test_filenames_are_sanitised(project, db_client: AsyncClient) -> None:
    ada, _, base = await project()
    res = await upload(db_client, base, ada.headers, "../../etc/pass<wd>.txt", b"hello")
    assert res.status_code == 201
    assert res.json()["filename"] == "pass_wd_.txt"
    assert res.json()["knowledge_path"] == "docs/normalized/pass-wd.md"


@pytest.mark.parametrize(
    ("name", "data", "problem"),
    [
        ("malware.exe", b"MZ", "unsupported_format"),
        ("noextension", b"x", "unsupported_format"),
        ("empty.txt", b"", "unreadable_document"),
    ],
)
async def test_rejected_uploads(project, db_client: AsyncClient, storage, name, data, problem) -> None:
    ada, _, base = await project()
    res = await upload(db_client, base, ada.headers, name, data)
    assert res.status_code == 422 and res.json()["type"].endswith(f"/{problem}")
    assert storage.objects == {}


async def test_upload_size_limit(project, db_client: AsyncClient, storage) -> None:
    ada, _, base = await project()
    res = await upload(db_client, base, ada.headers, "big.txt", b"x" * (25_000_000 + 1))
    assert res.status_code == 422 and res.json()["type"].endswith("/file_too_large")
    assert storage.objects == {}


async def test_original_is_removed_if_the_import_fails(project, db_client: AsyncClient, storage) -> None:
    ada, _, base = await project()
    # Fits the upload limit, but its markdown exceeds the 1 MB knowledge-file limit.
    res = await upload(db_client, base, ada.headers, "huge.txt", b"x" * 1_500_000)
    assert res.status_code == 422
    assert storage.objects == {}  # no orphaned original
    assert (await db_client.get(f"{base}/documents", headers=ada.headers)).json() == []


async def test_upload_permissions(project, db_client: AsyncClient, add_member, signup) -> None:
    ada, team, base = await project()
    guest = await signup(email="guest@example.com", name="Guest")
    eve = await signup(email="eve@example.com", name="Eve")
    await add_member(team["id"], guest.id, Role.GUEST)
    token = (
        await db_client.post("/v1/me/tokens", json={"name": "ro", "scopes": ["read"]}, headers=ada.headers)
    ).json()["token"]

    bob = await signup(email="bob@example.com", name="Bob")
    await add_member(team["id"], bob.id, Role.MEMBER)
    # Adding a project's external docs is setup work: owners and admins only.
    assert (await upload(db_client, base, bob.headers, "a.md", b"a")).status_code == 403
    assert (await upload(db_client, base, guest.headers, "a.md", b"a")).status_code == 403
    assert (await upload(db_client, base, eve.headers, "a.md", b"a")).status_code == 404
    read_only = {"Authorization": f"Bearer {token}"}
    assert (await upload(db_client, base, read_only, "a.md", b"a")).status_code == 403


async def test_unknown_document_is_404(project, db_client: AsyncClient) -> None:
    ada, _, base = await project()
    res = await db_client.get(f"{base}/documents/00000000-0000-0000-0000-000000000000", headers=ada.headers)
    assert res.status_code == 404


async def test_storage_not_configured_is_503(project, db_client: AsyncClient) -> None:
    ada, _, base = await project()
    app = db_client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides.pop(get_storage)
    app.state.storage = None
    res = await upload(db_client, base, ada.headers, "a.md", b"a")
    assert res.status_code == 503 and res.json()["type"].endswith("/storage_unavailable")
