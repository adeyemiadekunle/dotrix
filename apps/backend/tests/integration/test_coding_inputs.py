"""Messages a person sends a coding session while Kai works: steer the running turn, or queue the next one."""
import dataclasses
import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from dotrix_backend.modules.coding.inputs import (
    deliver_for_job,
    settle_steers,
    steer_states,
    take_steers,
)
from dotrix_backend.modules.coding.models import CodingInput, CodingRun, CodingRunStatus

from .test_coding import (  # noqa: F401  (fixtures)
    _asked,
    _save_key,
    _set_run,
    claude,
    coding,
    origin,
)


@pytest.fixture
def queued(db_client: AsyncClient, coding):  # noqa: F811
    """The coding world, with jobs able to queue the turns queued messages become (as in local mode)."""
    jobs = db_client._transport.app.state.jobs  # type: ignore[attr-defined]
    jobs.ctx = dataclasses.replace(jobs.ctx, jobs=jobs)
    return coding


async def _fx_asked(db_client: AsyncClient, coding) -> tuple[str, dict]:  # noqa: F811
    """A session on fx (OpenAI), its first turn waiting for approval."""
    ada, _, ws, kun, _, _ = coding
    await _save_key(db_client, ada.headers, "openai", "test-openai-personal-provider-key")
    db_client._transport.app.state.settings.coding_fx_model = "openai:gpt-6.1"  # type: ignore[attr-defined]
    base = f"{ws}/projects/{kun['id']}"
    issue = (await db_client.post(f"{base}/issues", headers=ada.headers, json={"type": "task", "title": "Refunds"})).json()
    run = await db_client.post(f"{base}/coding/issues/{issue['key']}/runs", json={"agent": "fx"}, headers=ada.headers)
    assert run.status_code == 201 and run.json()["agent"] == "fx", run.text
    return base, run.json()


def _ctx(db_client: AsyncClient):
    return db_client._transport.app.state.jobs.ctx  # type: ignore[attr-defined]


async def _send(db_client: AsyncClient, base: str, session_id: str, headers, kind: str, message: str, **extra):
    return await db_client.post(f"{base}/coding/sessions/{session_id}/inputs", headers=headers,
                                json={"client_id": str(uuid.uuid4()), "kind": kind, "message": message, **extra})


async def _inputs(db_client: AsyncClient, base: str, session_id: str, headers) -> list[dict]:
    res = await db_client.get(f"{base}/coding/sessions/{session_id}/inputs", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


async def _turns(db_client: AsyncClient, base: str, session_id: str, headers) -> list[dict]:
    return (await db_client.get(f"{base}/coding/sessions/{session_id}", headers=headers)).json()


async def test_queued_messages_become_one_next_turn_once_the_turn_finishes(db_client: AsyncClient, queued) -> None:
    ada, _, _, _, _, _ = queued
    base, run = await _asked(db_client, queued)
    session_id = run["session_id"]
    for text in ("Also handle partial refunds", "And add a changelog entry"):
        res = await _send(db_client, base, session_id, ada.headers, "queue", text)
        assert res.status_code == 201, res.text
        assert res.json()["status"] == "pending"
    # Waiting for approval: nothing moves, and only a cloud fx turn that's working can be steered.
    assert run["accepts_steering"] is False
    refused = await _send(db_client, base, session_id, ada.headers, "steer", "Mid-turn")
    assert refused.status_code == 409, refused.text
    assert await deliver_for_job(_ctx(db_client)) == 0
    await _set_run(db_client, run["id"], status=CodingRunStatus.PR_OPENED, finished_at=datetime.now(UTC))
    assert await deliver_for_job(_ctx(db_client)) == 1
    turns = await _turns(db_client, base, session_id, ada.headers)
    assert len(turns) == 2 and turns[1]["origin"] == "follow_up" and turns[1]["status"] == "awaiting_approval"
    assert "Also handle partial refunds\n\nAnd add a changelog entry" in turns[1]["brief"]
    items = await _inputs(db_client, base, session_id, ada.headers)
    assert {i["status"] for i in items} == {"delivered"} and {i["delivered_run_id"] for i in items} == {turns[1]["id"]}
    assert await deliver_for_job(_ctx(db_client)) == 0  # once


async def test_a_turn_that_was_stopped_or_failed_cancels_what_was_queued(db_client: AsyncClient, queued) -> None:
    ada, _, _, _, _, _ = queued
    base, run = await _asked(db_client, queued)
    await _send(db_client, base, run["session_id"], ada.headers, "queue", "Then the docs")
    await _set_run(db_client, run["id"], status=CodingRunStatus.STOPPED, finished_at=datetime.now(UTC))
    assert await deliver_for_job(_ctx(db_client)) == 0
    [item] = await _inputs(db_client, base, run["session_id"], ada.headers)
    assert item["status"] == "cancelled" and item["note"] == "The turn was stopped"
    assert len(await _turns(db_client, base, run["session_id"], ada.headers)) == 1


async def test_a_message_is_private_to_whoever_started_the_session_and_can_be_taken_back(db_client: AsyncClient, queued) -> None:
    ada, cat, _, _, _, _ = queued
    base, run = await _asked(db_client, queued)
    session_id = run["session_id"]
    # Cat may not instruct Kai here (403); someone who may gets 404 for a session that isn't theirs.
    assert (await _send(db_client, base, session_id, cat.headers, "queue", "Mine now")).status_code in (403, 404)
    assert (await db_client.get(f"{base}/coding/sessions/{session_id}/inputs", headers=cat.headers)).status_code in (403, 404)
    client_id = str(uuid.uuid4())
    body = {"client_id": client_id, "kind": "queue", "message": "Then the docs"}
    first = await db_client.post(f"{base}/coding/sessions/{session_id}/inputs", json=body, headers=ada.headers)
    again = await db_client.post(f"{base}/coding/sessions/{session_id}/inputs", json=body, headers=ada.headers)
    assert first.status_code == again.status_code == 201 and first.json()["id"] == again.json()["id"]
    other = await db_client.post(f"{base}/coding/sessions/{session_id}/inputs", headers=ada.headers,
                                 json={**body, "message": "Something else"})
    assert other.status_code == 409
    item = first.json()
    assert (await db_client.delete(f"{base}/coding/sessions/{session_id}/inputs/{item['id']}",
                                   headers=cat.headers)).status_code in (403, 404)
    taken = await db_client.delete(f"{base}/coding/sessions/{session_id}/inputs/{item['id']}", headers=ada.headers)
    assert taken.status_code == 200 and taken.json()["status"] == "cancelled"
    await _set_run(db_client, run["id"], status=CodingRunStatus.PR_OPENED, finished_at=datetime.now(UTC))
    assert await deliver_for_job(_ctx(db_client)) == 0  # nothing left to send


async def test_nothing_is_sent_to_a_session_kai_isnt_working_in(db_client: AsyncClient, queued) -> None:
    ada, _, _, _, _, _ = queued
    base, run = await _asked(db_client, queued)
    await _set_run(db_client, run["id"], status=CodingRunStatus.PR_OPENED, finished_at=datetime.now(UTC))
    res = await _send(db_client, base, run["session_id"], ada.headers, "queue", "Then the docs")
    assert res.status_code == 409 and "follow-up" in res.json()["detail"]


async def test_a_working_fx_turn_takes_steers_and_one_it_didnt_take_goes_to_the_next_turn(db_client: AsyncClient, queued) -> None:
    ada, _, _, _, _, _ = queued
    base, run = await _fx_asked(db_client, queued)
    session_id, run_id = run["session_id"], uuid.UUID(run["id"])
    await _set_run(db_client, run["id"], status=CodingRunStatus.RUNNING)
    [turn] = await _turns(db_client, base, session_id, ada.headers)
    assert turn["accepts_steering"] is True
    taken = (await _send(db_client, base, session_id, ada.headers, "steer", "Use the refunds table")).json()
    missed = (await _send(db_client, base, session_id, ada.headers, "steer", "And log each refund")).json()
    sessions = _ctx(db_client).session_factory
    # The worker drops both in the turn's inbox; the driver reports the first taken, the second never sent.
    assert [str(k) for k, _ in await take_steers(sessions, run_id)] == [taken["id"], missed["id"]]
    assert await take_steers(sessions, run_id) == []  # each once
    await steer_states(sessions, run_id, [(taken["id"], "sent", None), (taken["id"], "accepted", None),
                                          (taken["id"], "sent", None)])  # a late report never goes back
    states = {i["id"]: i for i in await _inputs(db_client, base, session_id, ada.headers)}
    assert states[taken["id"]]["status"] == "accepted" and states[missed["id"]]["status"] == "sending"
    # Taking it back is too late once Kai has it.
    late = await db_client.delete(f"{base}/coding/sessions/{session_id}/inputs/{taken['id']}", headers=ada.headers)
    assert late.status_code == 409
    await _set_run(db_client, run["id"], status=CodingRunStatus.PR_OPENED, finished_at=datetime.now(UTC))
    assert await deliver_for_job(_ctx(db_client)) == 1
    states = {i["id"]: i for i in await _inputs(db_client, base, session_id, ada.headers)}
    assert states[taken["id"]]["status"] == "delivered" and states[taken["id"]]["delivered_run_id"] == run["id"]
    assert states[missed["id"]]["kind"] == "queue" and states[missed["id"]]["status"] == "delivered"
    turns = await _turns(db_client, base, session_id, ada.headers)
    assert states[missed["id"]]["delivered_run_id"] == turns[1]["id"]
    assert "And log each refund" in turns[1]["brief"] and "Use the refunds table" not in turns[1]["brief"]


async def test_a_stopped_turn_cancels_the_steers_it_never_took(db_client: AsyncClient, queued) -> None:
    ada, _, _, _, _, _ = queued
    base, run = await _fx_asked(db_client, queued)
    await _set_run(db_client, run["id"], status=CodingRunStatus.RUNNING)
    await _send(db_client, base, run["session_id"], ada.headers, "steer", "Use the refunds table")
    sessions = _ctx(db_client).session_factory
    async with sessions() as session:
        stopped = await session.get(CodingRun, uuid.UUID(run["id"]), with_for_update=True)
        stopped.status = CodingRunStatus.STOPPED
        await settle_steers(session, stopped)
        await session.commit()
        [item] = list(await session.scalars(select(CodingInput).where(CodingInput.session_id == stopped.session_id)))
    assert item.status == "cancelled" and item.note == "The turn was stopped"


async def test_a_queued_message_whose_turn_is_refused_says_why(db_client: AsyncClient, queued) -> None:
    ada, _, _, _, _, _ = queued
    base, run = await _fx_asked(db_client, queued)
    await _send(db_client, base, run["session_id"], ada.headers, "queue", "Then the docs")
    db_client._transport.app.state.settings.coding_fx_model = None  # type: ignore[attr-defined]
    await _db_key_gone(db_client, ada.headers)
    await _set_run(db_client, run["id"], status=CodingRunStatus.PR_OPENED, finished_at=datetime.now(UTC))
    assert await deliver_for_job(_ctx(db_client)) == 0
    [item] = await _inputs(db_client, base, run["session_id"], ada.headers)
    assert item["status"] == "rejected" and "provider key" in item["note"], item
    assert len(await _turns(db_client, base, run["session_id"], ada.headers)) == 1


async def _db_key_gone(db_client: AsyncClient, headers) -> None:
    res = await db_client.delete("/v1/me/model-keys/openai", headers=headers)
    assert res.status_code in (200, 204), res.text
