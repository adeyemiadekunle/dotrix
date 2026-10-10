import hashlib
import io

import pytest
from httpx import AsyncClient
from openpyxl import Workbook

from dotrix_backend.core.storage import MemoryBlobStorage, get_storage
from dotrix_backend.modules.workspaces.models import Role


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


async def test_a_failed_conversion_is_recorded_and_the_original_kept(project, db_client: AsyncClient, storage) -> None:
    ada, _, base = await project()
    # Fits the upload limit, but its markdown exceeds the 1 MB knowledge-file limit.
    res = await upload(db_client, base, ada.headers, "huge.txt", b"x" * 1_500_000)
    assert res.status_code == 201
    doc = res.json()
    assert doc["status"] == "failed" and doc["error"]  # the knowledge service's reason, e.g. too large
    assert doc["knowledge_version"] == 0
    assert len(storage.objects) == 1  # the original stays downloadable
    missing = await db_client.get(f"{base}/knowledge/files/{doc['knowledge_path']}", headers=ada.headers)
    assert missing.status_code == 404


async def test_conversion_happens_after_the_upload_returns(project, db_client: AsyncClient) -> None:
    ada, _, base = await project()
    queued: list[tuple[str, dict]] = []

    class Recorder:
        async def enqueue(self, name: str, **kwargs) -> None:
            queued.append((name, kwargs))

    app = db_client._transport.app  # type: ignore[attr-defined]
    inline, app.state.jobs = app.state.jobs, Recorder()
    res = await upload(db_client, base, ada.headers, "spec.md", b"# Spec\n\nDrivers.")
    doc = res.json()
    assert res.status_code == 201 and doc["status"] == "converting" and doc["knowledge_version"] == 0
    assert queued == [("convert_document", {"document_id": doc["id"]})]

    # The job, later (here: run it now).
    await inline.enqueue(*queued[0][:1], **queued[0][1])
    done = (await db_client.get(f"{base}/documents/{doc['id']}", headers=ada.headers)).json()
    assert done["status"] == "ready" and done["knowledge_version"] == 1 and done["error"] is None
    md = (await db_client.get(f"{base}/knowledge/files/docs/normalized/spec.md", headers=ada.headers)).json()
    assert "Drivers." in md["content"]
    # A retried job doesn't convert it twice.
    await inline.enqueue(*queued[0][:1], **queued[0][1])
    again = (await db_client.get(f"{base}/documents/{doc['id']}", headers=ada.headers)).json()
    assert again["knowledge_version"] == 1


async def test_conversions_cut_off_by_a_restart_are_marked_failed(project, db_client: AsyncClient) -> None:
    from dotrix_backend.modules.documents.service import mark_interrupted_conversions

    ada, _, base = await project()

    class Nothing:
        async def enqueue(self, name: str, **kwargs) -> None:
            pass

    app = db_client._transport.app  # type: ignore[attr-defined]
    app.state.jobs = Nothing()
    doc = (await upload(db_client, base, ada.headers, "spec.md", b"# Spec")).json()
    await mark_interrupted_conversions(app.state.runner.session_factory)
    after = (await db_client.get(f"{base}/documents/{doc['id']}", headers=ada.headers)).json()
    assert after["status"] == "failed" and "restarted" in after["error"]


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


async def test_retry_a_failed_conversion(project, db_client: AsyncClient, storage, add_member, signup) -> None:
    ada, team, base = await project()
    doc = (await upload(db_client, base, ada.headers, "notes.txt", b"x" * 1_500_000)).json()
    assert doc["status"] == "failed"
    retry = f"{base}/documents/{doc['id']}/retry"
    # Members don't add documents, so they don't retry them either.
    cat = await signup(email="cat@example.com", name="Cat")
    await add_member(team["id"], cat.id, Role.MEMBER)
    assert (await db_client.post(retry, headers=cat.headers)).status_code == 403

    # Still too big: it fails again, with the reason.
    again = await db_client.post(retry, headers=ada.headers)
    assert again.status_code == 200 and again.json()["status"] == "failed" and again.json()["error"]
    # Whatever made it fail is fixed (here: the stored original): the retry converts it.
    (key,) = storage.objects
    storage.objects[key] = (b"# Notes\n\nShorter now.\n", "text/plain")
    done = (await db_client.post(retry, headers=ada.headers)).json()
    assert done["status"] == "ready" and done["error"] is None and done["knowledge_version"] == 1
    # Only a failed conversion can be retried.
    assert (await db_client.post(retry, headers=ada.headers)).status_code == 409


# -- rename, duplicate, delete ------------------------------------------------------------


async def test_rename_keeps_the_extension_and_the_markdown(project, db_client: AsyncClient) -> None:
    ada, _, base = await project()
    doc = (await upload(db_client, base, ada.headers, "notes.md", b"# Notes\n")).json()

    renamed = await db_client.patch(f"{base}/documents/{doc['id']}", json={"filename": "Meeting notes.md"}, headers=ada.headers)
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["filename"] == "Meeting notes.md"
    assert renamed.json()["knowledge_path"] == doc["knowledge_path"]  # agents still find it where it was
    original = await db_client.get(f"{base}/documents/{doc['id']}/original", headers=ada.headers)
    assert "Meeting%20notes.md" in original.headers["content-disposition"]

    other_type = await db_client.patch(f"{base}/documents/{doc['id']}", json={"filename": "notes.pdf"}, headers=ada.headers)
    assert other_type.status_code == 422


async def test_duplicate_copies_the_original_under_a_free_name(project, db_client: AsyncClient, storage) -> None:
    ada, _, base = await project()
    doc = (await upload(db_client, base, ada.headers, "spec.md", b"# Spec\n")).json()

    first = await db_client.post(f"{base}/documents/{doc['id']}/duplicate", headers=ada.headers)
    assert first.status_code == 201, first.text
    second = (await db_client.post(f"{base}/documents/{doc['id']}/duplicate", headers=ada.headers)).json()
    assert (first.json()["filename"], second["filename"]) == ("spec copy.md", "spec copy 2.md")
    assert first.json()["sha256"] == doc["sha256"] and first.json()["id"] != doc["id"]
    assert len(storage.objects) == 3
    copy = await db_client.get(f"{base}/documents/{first.json()['id']}/original", headers=ada.headers)
    assert copy.content == b"# Spec\n"


async def test_delete_removes_the_original_and_its_markdown(project, db_client: AsyncClient, storage) -> None:
    ada, team, base = await project()
    doc = (await upload(db_client, base, ada.headers, "old.md", b"# Old\n")).json()

    gone = await db_client.delete(f"{base}/documents/{doc['id']}", headers=ada.headers)
    assert gone.status_code == 204, gone.text
    assert (await db_client.get(f"{base}/documents/{doc['id']}", headers=ada.headers)).status_code == 404
    assert storage.objects == {}
    assert (await db_client.get(f"{base}/knowledge/files/{doc['knowledge_path']}", headers=ada.headers)).status_code == 404
    # A versioned delete: it can be restored from the file's history.
    restored = await db_client.post(f"{base}/knowledge/files/{doc['knowledge_path']}/restore", json={"version": 1}, headers=ada.headers)
    assert restored.status_code in (200, 201), restored.text
    audit = (await db_client.get(f"/v1/workspaces/{team['id']}/audit", headers=ada.headers)).json()
    assert "document.deleted" in {a["action"] for a in audit}


async def test_deleting_one_upload_keeps_markdown_another_upload_made(project, db_client: AsyncClient) -> None:
    ada, _, base = await project()
    first = (await upload(db_client, base, ada.headers, "plan.md", b"# Plan v1\n")).json()
    await upload(db_client, base, ada.headers, "plan.md", b"# Plan v2\n")  # same name: the same markdown file

    assert (await db_client.delete(f"{base}/documents/{first['id']}", headers=ada.headers)).status_code == 204
    md = await db_client.get(f"{base}/knowledge/files/{first['knowledge_path']}", headers=ada.headers)
    assert md.status_code == 200 and "Plan v2" in md.json()["content"]


async def test_only_owners_and_admins_change_documents(project, db_client: AsyncClient, add_member, signup) -> None:
    ada, team, base = await project()
    doc = (await upload(db_client, base, ada.headers, "notes.md", b"# Notes\n")).json()
    grace = await signup(email="grace@example.com", name="Grace")
    await add_member(team["id"], grace.id, Role.MEMBER)
    assert (await db_client.patch(f"{base}/documents/{doc['id']}", json={"filename": "x.md"}, headers=grace.headers)).status_code == 403
    assert (await db_client.post(f"{base}/documents/{doc['id']}/duplicate", headers=grace.headers)).status_code == 403
    assert (await db_client.delete(f"{base}/documents/{doc['id']}", headers=grace.headers)).status_code == 403
