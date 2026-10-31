"""Sandbox network (owners and admins choose the hosts Kai's sandboxes may reach) and sandboxes that sleep
between turns (Docker Cloud), through the API and the coding worker, with a fake sandbox."""
import dataclasses
import uuid
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import select

from apps.backend.tests.integration.test_coding import (  # noqa: F401  (fixtures)
    ScriptedClaude,
    TranscriptSandbox,
    _approve,
    claude,
    coding,
    origin,
)
from dotrix_backend.modules.audit.models import AuditEvent
from dotrix_backend.modules.coding.models import CodingSession
from dotrix_backend.modules.coding.warm import WarmPool


class SleepingSandbox(TranscriptSandbox):
    """A sandbox that sleeps between turns, as Docker Cloud's do: asleep keeps its files; waking returns it."""

    kind = "fake-cloud"
    sleeps = True

    def __init__(self, agent) -> None:
        super().__init__(agent)
        self.allowed: list[list[str]] = []
        self.boxes: dict[str, object] = {}
        self.asleep: set[str] = set()
        self.woken = 0
        self.discarded: list[str] = []
        self.swept: list[set[str]] = []

    async def open(self, run_id, source, tool, model_key, *, allow=()):
        self.allowed.append(list(allow))
        return await super().open(run_id, source, tool, model_key)

    def handle(self, box):
        ref = uuid.uuid4().hex
        self.boxes[ref] = box
        return {"kind": self.kind, "sandbox": ref}

    async def sleep(self, box) -> None:
        self.asleep.update(ref for ref, b in self.boxes.items() if b is box)

    async def wake(self, handle, tool, key):
        self.woken += 1
        self.asleep.discard(handle["sandbox"])
        return self.boxes.get(handle["sandbox"])

    async def discard(self, handle) -> None:
        self.discarded.append(handle["sandbox"])
        self.asleep.discard(handle["sandbox"])

    async def sweep(self, keep, min_age=0) -> int:
        self.swept.append(set(keep))
        return 0


async def test_owners_and_admins_choose_the_hosts_sandboxes_may_reach(
    db_client: AsyncClient, coding, db_session,  # noqa: F811
) -> None:
    ada, cat, ws, kun, mob, _ = coding
    workspace_url, project_url = f"{ws}/coding/network", f"{ws}/projects/{kun['id']}/coding/network"
    empty = (await db_client.get(workspace_url, headers=cat.headers)).json()  # anyone may read it
    assert empty["effective"] == [] and "npm" in empty["available_presets"]

    # A member can't change it, even one allowed to instruct Kai; owners and admins can.
    assert (await db_client.put(workspace_url, json={"hosts": ["evil.example.com"]}, headers=cat.headers)).status_code == 403
    assert (await db_client.put(project_url, json={"hosts": ["evil.example.com"]}, headers=cat.headers)).status_code == 403
    for bad in ("https://registry.npmjs.org", "10.0.0.1", "registry.npmjs.org:443", "*.com", "no_dots"):
        refused = await db_client.put(workspace_url, json={"hosts": [bad]}, headers=ada.headers)
        assert refused.status_code == 409, (bad, refused.text)
    assert (await db_client.put(workspace_url, json={"presets": ["nope"]}, headers=ada.headers)).status_code == 409

    saved = await db_client.put(workspace_url, json={"presets": ["npm"], "hosts": [" API.Example.com. ", "api.example.com"]},
                                headers=ada.headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["hosts"] == ["api.example.com"]
    assert saved.json()["effective"] == ["registry.npmjs.org", "registry.yarnpkg.com", "api.example.com"]
    project = (await db_client.put(project_url, json={"hosts": ["*.staging.example.com", "api.example.com"]},
                                   headers=ada.headers)).json()
    assert project["hosts"] == ["*.staging.example.com", "api.example.com"]
    assert project["effective"] == ["registry.npmjs.org", "registry.yarnpkg.com", "api.example.com",
                                    "*.staging.example.com"]  # the workspace's, then the project's
    other = (await db_client.get(f"{ws}/projects/{mob['id']}/coding/network", headers=ada.headers)).json()
    assert other["effective"] == ["registry.npmjs.org", "registry.yarnpkg.com", "api.example.com"]

    audited = list(await db_session.scalars(select(AuditEvent).where(AuditEvent.action == "sandbox_network.updated")
                                            .order_by(AuditEvent.created_at)))
    assert [e.details["scope"] for e in audited] == ["workspace", "project"]
    assert audited[0].details["added"] == ["registry.npmjs.org", "registry.yarnpkg.com", "api.example.com"]
    assert str(audited[0].actor_user_id) == ada.id

    cleared = (await db_client.put(workspace_url, json={}, headers=ada.headers)).json()
    assert cleared["effective"] == [] and cleared["presets"] == []


async def test_a_session_sleeps_between_turns_and_wakes_for_the_next(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude, agent_script, db_session,  # noqa: F811
) -> None:
    ada, _, ws, kun, _, _ = coding
    app = db_client._transport.app  # type: ignore[attr-defined]
    jobs = app.state.jobs
    sandbox = SleepingSandbox(claude)
    # No warm sandboxes kept: each turn's sandbox goes to sleep as soon as the turn ends.
    worker = dataclasses.replace(jobs.ctx.coding, sandbox=sandbox, pool=WarmPool(3600, 0))
    jobs.ctx = dataclasses.replace(jobs.ctx, coding=worker)
    claude.found_transcript, claude.argvs = [], []
    base = f"{ws}/projects/{kun['id']}"
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Refunds"}, headers=ada.headers)).json()
    agent_script.say("Fine.", "Fine again.", "And again.", "Once more.")

    claude.edits = {"src/refunds.py": "def refund(amount):\n    return amount\n"}
    first = await _approve(db_client, base, (await db_client.post(
        f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json(), ada.headers)
    assert first["status"] == "pr_opened" and sandbox.opened == 1 and sandbox.allowed == [[]]
    session_id = uuid.UUID(first["session_id"])
    row = await db_session.scalar(select(CodingSession).where(CodingSession.id == session_id)
                                  .execution_options(populate_existing=True))
    assert row.sandbox_handle["kind"] == "fake-cloud" and row.sandbox_slept_at is not None
    assert len(sandbox.asleep) == 1

    # The next turn wakes it: no new sandbox, its files as they were.
    turns = f"{base}/coding/sessions/{session_id}/turns"
    claude.edits = {"src/refunds.py": "def refund(amount):\n    assert amount > 0\n    return amount\n"}
    second = await _approve(db_client, base, (await db_client.post(
        turns, json={"message": "Only positive"}, headers=ada.headers)).json(), ada.headers)
    assert second["status"] == "pr_opened" and sandbox.opened == 1 and sandbox.woken == 1
    assert any("woken from the last turn" in e["text"] for e in second["events"]), [e["text"] for e in second["events"]]
    assert claude.found_transcript[1] == "turn 1\n"

    # An owner allows a host: the sleeping sandbox (opened without it) isn't reused; a new one gets it.
    await db_client.put(f"{ws}/coding/network", json={"presets": ["pypi"]}, headers=ada.headers)
    claude.edits = {"src/refunds.py": "def refund(amount):\n    assert amount > 0, 'positive'\n    return amount\n"}
    third = await _approve(db_client, base, (await db_client.post(
        turns, json={"message": "Say why"}, headers=ada.headers)).json(), ada.headers)
    assert third["status"] == "pr_opened" and sandbox.opened == 2 and len(sandbox.discarded) == 1
    assert sandbox.allowed[-1] == ["pypi.org", "files.pythonhosted.org"]

    # Closed by hand: the sweep deletes its sleeping sandbox and forgets it.
    assert (await db_client.post(f"{base}/coding/sessions/{session_id}/close", headers=ada.headers)).status_code == 204
    await worker.sweep_sandboxes()
    assert len(sandbox.discarded) == 2 and sandbox.swept[-1] == set()
    row = await db_session.scalar(select(CodingSession).where(CodingSession.id == session_id)
                                  .execution_options(populate_existing=True))
    assert row.sandbox_handle is None
