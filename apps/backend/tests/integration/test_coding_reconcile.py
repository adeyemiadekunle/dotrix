"""The coding reconciler judges a run only by its current, non-discarded dispatch."""
import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils.compat import uuid7

from dotrix_backend.modules.agents.queue import RunQueue
from dotrix_backend.modules.coding.models import CodingRun, CodingRunStatus
from dotrix_backend.modules.execution.models import RunDispatch
from dotrix_backend.modules.execution.service import RunDispatcher

from .test_observe import _coding_run, _personal_ws


async def _setup(signup, db_client: AsyncClient, db_session: AsyncSession, redis, **run_kw):
    ada = await signup()
    ws = await _personal_ws(db_client, ada.headers)
    base = f"/v1/workspaces/{ws['id']}"
    project = (
        await db_client.post(f"{base}/projects", json={"key": "KUN", "name": "Kunemi"}, headers=ada.headers)
    ).json()
    issue = (
        await db_client.post(f"{base}/projects/{project['id']}/issues", json={"title": "Refunds"}, headers=ada.headers)
    ).json()
    run = _coding_run(ws["id"], project["id"], issue["id"], ada, status=CodingRunStatus.RUNNING, **run_kw)
    db_session.add(run)
    await db_session.commit()
    name = f"dotrix:test:{uuid.uuid4().hex[:8]}"
    queue = RunQueue(redis, queue_name=name)
    factory = db_client._transport.app.state.runner.session_factory  # type: ignore[attr-defined]
    return run, name, RunDispatcher(factory, queue), factory


def _dispatch(run: CodingRun, queue_name: str, generation: int, accepted_ago: timedelta, **kw) -> RunDispatch:
    now = datetime.now(UTC)
    return RunDispatch(
        id=uuid7(), workspace_id=run.workspace_id, coding_run_id=run.id, generation=generation,
        queue_name=queue_name, payload={}, created_at=now, next_attempt_at=now, publish_attempts=0,
        accepted_at=now - accepted_ago, **kw,
    )


async def _status(factory, run: CodingRun) -> CodingRunStatus:
    async with factory() as session:
        return (await session.get(CodingRun, run.id)).status


async def test_an_older_dispatch_does_not_flag_a_run_working_under_a_newer_one(
    signup, db_client: AsyncClient, db_session: AsyncSession, redis
) -> None:
    run, name, dispatcher, factory = await _setup(signup, db_client, db_session, redis, dispatch_generation=2)
    db_session.add(_dispatch(run, name, 1, timedelta(minutes=10)))
    db_session.add(_dispatch(run, name, 2, timedelta(seconds=0)))
    await db_session.commit()
    assert await dispatcher.reconcile_coding() == 0
    assert await _status(factory, run) is CodingRunStatus.RUNNING


async def test_a_discarded_dispatch_does_not_flag_a_run(
    signup, db_client: AsyncClient, db_session: AsyncSession, redis
) -> None:
    run, name, dispatcher, factory = await _setup(signup, db_client, db_session, redis, dispatch_generation=1)
    db_session.add(_dispatch(run, name, 1, timedelta(minutes=10), discarded_at=datetime.now(UTC)))
    await db_session.commit()
    assert await dispatcher.reconcile_coding() == 0
    assert await _status(factory, run) is CodingRunStatus.RUNNING


async def test_the_current_dispatch_whose_job_is_gone_still_flags_the_run(
    signup, db_client: AsyncClient, db_session: AsyncSession, redis
) -> None:
    run, name, dispatcher, factory = await _setup(signup, db_client, db_session, redis, dispatch_generation=1)
    db_session.add(_dispatch(run, name, 1, timedelta(minutes=10)))
    await db_session.commit()
    assert await dispatcher.reconcile_coding() == 1
    assert await _status(factory, run) is CodingRunStatus.RECOVERY_REQUIRED
