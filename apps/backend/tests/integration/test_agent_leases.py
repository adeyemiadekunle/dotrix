"""Durable chat runs: each attempt holds a lease its worker renews; a run whose lease lapses (its
worker stopped) goes on from its last checkpoint, at most three attempts a step, then is
interrupted for the person to continue. A resumed attempt never runs a cut-off write again
unasked: the cut-off call says so, and any change repeated waits for approval."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from dotrix_backend.modules.agents.models import AgentRun, RunStatus
from dotrix_backend.modules.agents.storage_backend import PlatformKnowledgeBackend
from dotrix_backend.modules.execution.models import RunDispatch
from dotrix_backend.modules.execution.service import expire_agent_leases
from dotrix_engine.testing import tool_call


class WorkerDied(BaseException):
    """The worker's process ending mid-step (nothing in the run gets to handle it)."""


async def _team(db_client: AsyncClient, signup, create_team, add_member):
    ada = await signup()
    team = await create_team(ada.headers)
    ws = f"/v1/workspaces/{team['id']}"
    await db_client.patch(ws, json={"approval_mode_cap": "accept_edits"}, headers=ada.headers)
    project = (await db_client.post(f"{ws}/projects", json={"key": "KUN", "name": "K"}, headers=ada.headers)).json()
    return ada, f"{ws}/projects/{project['id']}"


def _factory(db_client: AsyncClient):
    return db_client._transport.app.state.jobs.ctx.session_factory  # type: ignore[attr-defined]


async def _lapse(db_client: AsyncClient, run_id: str, **values) -> None:
    async with _factory(db_client)() as session:
        await session.execute(update(AgentRun).where(AgentRun.id == uuid.UUID(run_id)).values(
            status=RunStatus.RUNNING, lease_expires_at=datetime.now(UTC) - timedelta(seconds=5), **values))
        await session.commit()


async def test_a_lapsed_lease_resumes_the_run_then_interrupts_it(
    db_client: AsyncClient, signup, create_team, add_member, agent_script
) -> None:
    ada, base = await _team(db_client, signup, create_team, add_member)
    agent_script.say("Hello.")
    run = (await db_client.post(f"{base}/agent/runs", headers=ada.headers, json={"message": "Hi"})).json()
    assert run["status"] == "completed"
    run_id = uuid.UUID(run["id"])
    async with _factory(db_client)() as session:
        row = await session.get(AgentRun, run_id)
        assert row.lease_token == 1 and row.lease_expires_at is None  # held while it worked, released after
        session.add(RunDispatch(
            id=uuid.uuid4(), workspace_id=row.workspace_id, agent_run_id=row.id, generation=1, queue_name="q",
            payload={"kind": "start", "message": "Hi"}, created_at=datetime.now(UTC),
            next_attempt_at=datetime.now(UTC), publish_attempts=0, accepted_at=datetime.now(UTC),
        ))
        await session.commit()

    # Its worker stopped: the sweep queues the same step again, from its checkpoint, flagged as recovered.
    await _lapse(db_client, run["id"], dispatch_generation=1)
    assert await expire_agent_leases(_factory(db_client), queue_name="q") == 1
    async with _factory(db_client)() as session:
        row = await session.get(AgentRun, run_id)
        assert row.status is RunStatus.QUEUED and row.dispatch_generation == 2
        again = await session.scalar(select(RunDispatch).where(RunDispatch.agent_run_id == run_id,
                                                               RunDispatch.generation == 2))
        assert again.payload == {"kind": "start", "message": "Hi", "recovered": True, "attempt": 2}
        again.accepted_at = datetime.now(UTC)
        await session.commit()
    await _lapse(db_client, run["id"])
    await expire_agent_leases(_factory(db_client), queue_name="q")  # attempt 3
    async with _factory(db_client)() as session:
        third = await session.scalar(select(RunDispatch).where(RunDispatch.agent_run_id == run_id,
                                                               RunDispatch.generation == 3))
        third.accepted_at = datetime.now(UTC)
        await session.commit()
    await _lapse(db_client, run["id"])
    await expire_agent_leases(_factory(db_client), queue_name="q")
    stopped = (await db_client.get(f"{base}/agent/runs/{run['id']}", headers=ada.headers)).json()
    assert stopped["status"] == "failed" and stopped["error_kind"] == "interrupted"
    assert "stopped 3 times" in stopped["error"]
    audit = [e["action"] for e in (await db_client.get(f"{base.rsplit('/projects', 1)[0]}/audit",
                                                       headers=ada.headers)).json()]
    assert audit.count("agent_run.recovered") == 2 and "agent_run.interrupted" in audit

    # A lease that's still being renewed is left alone.
    async with _factory(db_client)() as session:
        await session.execute(update(AgentRun).where(AgentRun.id == run_id).values(
            status=RunStatus.RUNNING, lease_expires_at=datetime.now(UTC) + timedelta(seconds=60)))
        await session.commit()
    assert await expire_agent_leases(_factory(db_client), queue_name="q") == 0


async def test_a_run_cut_off_mid_write_resumes_without_writing_twice_unasked(
    db_client: AsyncClient, signup, create_team, add_member, agent_script, monkeypatch
) -> None:
    ada, base = await _team(db_client, signup, create_team, add_member)
    real = PlatformKnowledgeBackend.awrite

    async def dies(self, file_path: str, content: str):
        await real(self, file_path, content)  # the write landed, then the worker's process ended
        raise WorkerDied

    monkeypatch.setattr(PlatformKnowledgeBackend, "awrite", dies)
    agent_script.say(tool_call("write_file", file_path="/dotrix/roadmap.md", content="# The plan"), "Written.")
    with pytest.raises(WorkerDied):
        await db_client.post(f"{base}/agent/runs", headers=ada.headers, json={
            "message": "Write the plan down", "approval_mode": "accept_edits",
        })
    monkeypatch.setattr(PlatformKnowledgeBackend, "awrite", real)
    async with _factory(db_client)() as session:
        run_id = await session.scalar(select(AgentRun.id).where(AgentRun.message == "Write the plan down"))
    await _lapse(db_client, str(run_id))
    await expire_agent_leases(_factory(db_client), queue_name="q")  # no dispatch step (local mode): interrupted
    stopped = (await db_client.get(f"{base}/agent/runs/{run_id}", headers=ada.headers)).json()
    assert stopped["error_kind"] == "interrupted"

    # Continued: the cut-off write isn't run again; the agent is told, and what it repeats waits.
    model = agent_script.say(
        tool_call("write_file", file_path="/dotrix/roadmap.md", content="# The plan"), "Waiting for approval.",
    )
    resumed = await db_client.post(f"{base}/agent/runs/{run_id}/continue", headers=ada.headers, json={})
    assert resumed.status_code == 200, resumed.text
    said = [m.content for m in model.received[0] if m.type == "tool"]
    assert said and said[-1].startswith("Cut off:")
    run = (await db_client.get(f"{base}/agent/runs/{run_id}", headers=ada.headers)).json()
    assert run["status"] == "awaiting_approval", run  # Accept edits was asked; a recovered attempt asks
    assert [a["tool"] for a in run["approvals"]] == ["write_file"]
