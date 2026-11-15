"""Profile admission, immutable approvals, and runner gates with disposable local transport."""
import pytest

from apps.backend.tests.integration.test_coding import (  # noqa: F401
    _git,
    _local_runner,
    checkout,
    claude,
    coding,
    origin,
)


async def configure(client, base, headers, **values):
    return await client.put(base + "/coding/environment", headers=headers,
        json={"revision": 0, "enabled": True, "name": "Python checks", **values})


async def ask(client, base, headers):
    issue = (await client.post(base + "/issues", headers=headers,
        json={"type": "task", "title": "Add refund"})).json()
    response = await client.post(f"{base}/coding/issues/{issue['key']}/runs", headers=headers, json={})
    assert response.status_code == 201, response.text
    return response.json()


async def execute(client, base, headers, run):
    response = await client.post(f"{base}/coding/runs/{run['id']}/decision", headers=headers, json={"decision": "approve"})
    assert response.status_code == 200, response.text
    return (await client.get(f"{base}/coding/runs/{run['id']}", headers=headers)).json()


async def test_administrator_version_checks_and_pinned_approval(db_client, coding, db_session):  # noqa: F811
    from dotrix_backend.modules.coding.models import CodingRun

    ada, cat, ws, project, _, _ = coding
    base = f"{ws}/projects/{project['id']}"
    assert (await configure(db_client, base, cat.headers)).status_code == 403
    first = await configure(db_client, base, ada.headers, setup_script="true")
    assert first.status_code == 200 and first.json()["revision"] == 1
    assert (await configure(db_client, base, ada.headers)).status_code == 409
    run = await ask(db_client, base, ada.headers)
    assert "revision 1" in run["brief"]
    assert (await configure(db_client, base, ada.headers, revision=1, setup_script="exit 7")).status_code == 200
    stored = await db_session.get(CodingRun, run["id"])
    assert stored.environment_snapshot["setup_script"] == "true"
    assert stored.environment_snapshot["revision"] == 1
    other = (await db_client.get(f"{ws}/projects/{coding[4]['id']}/coding/environment", headers=ada.headers)).json()
    assert other["revision"] == 0 and not other["enabled"]


@pytest.mark.parametrize(("setup", "verification", "message"), [
    ("echo secret-marker; exit 9", "", "Environment setup failed"),
    ("printf changed > unreviewed.txt", "", "changed repository files"),
    ("true", "exit 8", "Environment verification failed"),
    ("printf changed > src/payments.py; git add .; git -c user.name=Test -c user.email=test@example.invalid commit -qm hidden",
     "", "changed repository files"),
])
async def test_failed_environment_never_publishes(db_client, coding, claude, github, setup, verification, message):  # noqa: F811
    ada, _, ws, project, _, sandbox = coding
    sandbox.kind = "docker"  # Scripted transport only; this does not claim real container isolation.
    base = f"{ws}/projects/{project['id']}"
    assert (await configure(db_client, base, ada.headers, setup_script=setup, verify_script=verification)).status_code == 200
    claude.edits = {"src/payments.py": "def refund(amount):\n    return amount\n"}
    result = await execute(db_client, base, ada.headers, await ask(db_client, base, ada.headers))
    assert result["status"] == "failed" and message in result["error"]
    assert not github.pulls and not result["files_changed"]
    if message != "Environment verification failed":
        assert not claude.briefs
    assert "secret-marker" not in str(result["events"]) and "secret-marker" not in result["error"]


async def test_successful_environment_keeps_manual_changes_unpublished(db_client, coding, claude, github):  # noqa: F811
    ada, _, ws, project, _, sandbox = coding
    sandbox.kind = "docker"
    base = f"{ws}/projects/{project['id']}"
    assert (await configure(db_client, base, ada.headers, setup_script="python3 --version",
                           verify_script="python3 -B -c 'from src.payments import refund; assert refund(7)==7'")).status_code == 200
    claude.edits = {"src/payments.py": "def refund(amount):\n    return amount\n"}
    result = await execute(db_client, base, ada.headers, await ask(db_client, base, ada.headers))
    assert result["status"] == "changes_ready", result.get("error")
    assert not github.pulls
    assert {x["path"] for x in result["files_changed"]} == {"src/payments.py"}
    steps = [e["text"] for e in result["events"]]
    assert "Environment setup passed" in steps and "Environment verification passed" in steps


async def test_profile_refuses_unisolated_cloud_process(db_client, coding, claude):  # noqa: F811
    ada, _, ws, project, _, _ = coding
    base = f"{ws}/projects/{project['id']}"
    await configure(db_client, base, ada.headers, setup_script="true")
    result = await execute(db_client, base, ada.headers, await ask(db_client, base, ada.headers))
    assert result["status"] == "failed" and "isolated sandbox" in result["error"]
    assert not claude.briefs


async def test_native_sessions_do_not_receive_cloud_setup(db_client, coding, checkout, tmp_path, db_session):  # noqa: F811
    from dotrix_backend.modules.coding.models import CodingRun

    ada, _, ws, project, _, _ = coding
    base = f"{ws}/projects/{project['id']}"
    await configure(db_client, base, ada.headers, setup_script="exit 77")
    runner = _local_runner(db_client, coding, checkout, tmp_path, "true")
    await runner.register()
    issue = (await db_client.post(base + "/issues", headers=ada.headers,
        json={"type": "task", "title": "Local work"})).json()
    response = await db_client.post(f"{base}/coding/issues/{issue['key']}/runs", headers=ada.headers,
        json={"location": "local"})
    assert response.status_code == 201, response.text
    stored = await db_session.get(CodingRun, response.json()["id"])
    assert stored.environment_snapshot is None and "exit 77" not in stored.brief


async def test_only_operator_reviewed_immutable_images_can_be_selected(db_client, coding):  # noqa: F811
    ada, _, ws, project, _, sandbox = coding
    sandbox.kind = "docker"
    base = f"{ws}/projects/{project['id']}"
    image = "registry.example.com/team/coding@sha256:" + "a" * 64
    assert (await configure(db_client, base, ada.headers, image="registry.example.com/team/coding:latest")).status_code == 422
    assert (await configure(db_client, base, ada.headers, image=image)).status_code == 409
    settings = db_client._transport.app.state.settings
    settings.coding_environment_images = [image]
    saved = await configure(db_client, base, ada.headers, image=image)
    assert saved.status_code == 200 and saved.json()["image_policy"] == "approved"
    assert (await db_client.get(base + "/coding/environment", headers=ada.headers)).json()["available_images"] == [image]
    admitted = await ask(db_client, base, ada.headers)
    settings.coding_environment_images = []
    failed = await execute(db_client, base, ada.headers, admitted)
    assert failed["status"] == "failed" and "no longer approved" in failed["error"]
    issue = (await db_client.post(base + "/issues", headers=ada.headers, json={"type": "task", "title": "Revoked image"})).json()
    assert (await db_client.post(f"{base}/coding/issues/{issue['key']}/runs", headers=ada.headers, json={})).status_code == 409


@pytest.mark.parametrize("already_resolved", [False, True])
async def test_resolved_image_is_pinned_and_used_for_worker_execution(db_client, coding, claude, db_session, already_resolved):  # noqa: F811
    ada, _, ws, project, _, sandbox = coding
    sandbox.kind = "docker"
    sandbox.image = "sha256:" + "b" * 64
    calls = []

    async def pin_image(reference):
        calls.append(reference)
        return sandbox  # Scripted transport; immutable resolution has its own unit test.

    sandbox.pin_image = pin_image
    base = f"{ws}/projects/{project['id']}"
    await configure(db_client, base, ada.headers, setup_script="true")
    claude.edits = {"src/payments.py": "def refund(amount):\n    return amount\n"}
    asked = await ask(db_client, base, ada.headers)
    if already_resolved:
        from dotrix_backend.modules.coding.models import CodingRun

        stored = await db_session.get(CodingRun, asked["id"])
        stored.environment_image_id = sandbox.image
        await db_session.commit()
    result = await execute(db_client, base, ada.headers, asked)
    assert result["status"] == "changes_ready", result.get("error")
    assert result["environment_image_id"] == "sha256:" + "b" * 64
    assert calls == [sandbox.image if already_resolved else db_client._transport.app.state.settings.coding_image]
