"""Private specialist history, using real Postgres, the scheduler and both chat runtimes."""
import asyncio
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import delete, select, update
from uuid_utils.compat import uuid7

from apps.backend.tests.integration.test_runtime_tools import model_server
from dotrix_backend.core.email import get_email_sender
from dotrix_backend.core.errors import Conflict, Forbidden
from dotrix_backend.core.jobs import InlineJobs, JobContext
from dotrix_backend.core.security import create_access_token
from dotrix_backend.core.storage import get_storage, optional_storage
from dotrix_backend.jobs import JOBS
from dotrix_backend.main import create_app
from dotrix_backend.modules.agents import fx_pilot
from dotrix_backend.modules.agents.delegation import DelegationService
from dotrix_backend.modules.agents.models import (
    AgentApproval,
    AgentRun,
    AgentSpecialistSession,
    RunKind,
    RunStatus,
    WorkMode,
)
from dotrix_backend.modules.agents.runner import _LEASE, AgentRunner
from dotrix_backend.modules.agents.specialist_sessions import (
    _current_policy,
    specialist_history,
)
from dotrix_backend.modules.agents.usage import TokenUsage
from dotrix_backend.modules.projects.models import Project, ProjectAccessLevel, ProjectSource
from dotrix_backend.modules.workspaces.models import Membership, Role
from dotrix_engine.delegation import SpecialistBatch, SpecialistResult
from dotrix_engine.testing import ScriptedChatModel, tool_call

pytest_plugins = ["apps.backend.tests.integration.test_runtime_tools"]


def _batch(brief: str, agent: str = "research", *, changes_project: bool = False) -> SpecialistBatch:
    return SpecialistBatch(tasks=[{"key": "task", "agent": agent, "brief": brief, "expected_result": "Findings",
                                   "changes_project": changes_project}])


async def test_private_sessions_serialize_work_and_resume_with_saved_history(nova_pilot_world, monkeypatch):
    from dotrix_backend.modules.agents import specialist_sessions

    root, sessions, secrets = nova_pilot_world
    async with sessions() as session:
        people = list(await session.scalars(select(Membership).where(Membership.workspace_id == root.workspace_id)))
        colleague = next(member.user_id for member in people if member.user_id != root.requested_by_id)
        now = datetime.now(UTC)
        project = Project(id=uuid7(), workspace_id=root.workspace_id, key="OTHER", name="Other",
                          source=ProjectSource.DOCS_ONLY, created_by_id=root.requested_by_id)
        session.add(project)
        await session.flush()

        def parent(*, owner=root.requested_by_id, thread=root.thread_id, project_id=root.project_id):
            return AgentRun(id=uuid7(), workspace_id=root.workspace_id, project_id=project_id,
                            thread_id=thread, requested_by_id=owner, kind=RunKind.CHAT,
                            status=RunStatus.RUNNING, message="Ask the team", work_mode=WorkMode.DISCUSS,
                            orchestration=True, lease_token=1, lease_expires_at=now + timedelta(minutes=5),
                            created_at=now, updated_at=now)

        same, other_thread, other_owner, other_role, other_project, writer = (
            parent(), parent(thread=uuid7()), parent(owner=colleague), parent(), parent(project_id=project.id), parent()
        )
        session.add_all([same, other_thread, other_owner, other_role, other_project, writer])
        await session.commit()
    dispatched = []

    async def dispatch(run_id, payload):
        dispatched.append((run_id, payload))

    runner = SimpleNamespace(session_factory=sessions, secrets=secrets, queue=None, stop_reasons=None,
                             settings=SimpleNamespace(specialist_continuity=True), _dispatch=dispatch)
    scheduler = DelegationService(runner)
    await asyncio.gather(*(scheduler.submit(root.workspace_id, parent.id, 1, "call", _batch("Concurrent research"))
                           for parent in (root, same)))
    for parent, agent in [(other_thread, "research"), (other_owner, "research"),
                          (other_role, "architecture"), (other_project, "research")]:
        await scheduler.submit(root.workspace_id, parent.id, 1, "call", _batch(f"Work for {parent.id}", agent))
    await scheduler.submit(root.workspace_id, writer.id, 1, "call", _batch("Update project", changes_project=True))
    async with sessions() as session:
        children = {child.parent_run_id: child for child in await session.scalars(select(AgentRun).where(
            AgentRun.workspace_id == root.workspace_id, AgentRun.parent_run_id.in_(
                [root.id, same.id, other_thread.id, other_owner.id, other_role.id, other_project.id, writer.id])))}
        ids = [children[parent.id].specialist_session_id for parent in (
            root, same, other_thread, other_owner, other_role, other_project)]
        assert None not in ids and ids[0] == ids[1] and len(set(ids)) == 5
        assert children[writer.id].specialist_session_id is None
        assert len(list(await session.scalars(select(AgentSpecialistSession.id).where(
            AgentSpecialistSession.workspace_id == root.workspace_id)))) == 5
    # Turning the flag off cannot silently remove the history from already-created tasks.
    runner.settings.specialist_continuity = False
    await scheduler.wait(root.workspace_id, root.id, 1, {"interrupt": "call"})
    await scheduler.wait(root.workspace_id, same.id, 1, {"interrupt": "call"})
    async with sessions() as session:
        first = await session.get(AgentRun, children[root.id].id)
        second = await session.get(AgentRun, children[same.id].id)
        assert first.status is RunStatus.QUEUED and second.status is RunStatus.WAITING_DEPENDENCY
        first.status, first.finished_at = RunStatus.COMPLETED, datetime.now(UTC)
        first.task_result = SpecialistResult(summary="Private finding: use PostgreSQL").model_dump(mode="json")
        first.reply = "The investigation is complete."
        await session.commit()
    await scheduler.completed(root.workspace_id, first.id)
    async with sessions() as session:
        second = await session.get(AgentRun, second.id)
        assert second.status is RunStatus.QUEUED
        assert second.specialist_history == {"version": 1, "ids": [str(first.id)], "omitted": False,
                                             "policy": first.specialist_history["policy"]}
        second.status, second.lease_token = RunStatus.RUNNING, 2
        second.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        await session.commit()
    first_history = await specialist_history(sessions, workspace_id=root.workspace_id, run_id=second.id, token=2)
    assert "Private finding: use PostgreSQL" in first_history and "untrusted evidence" in first_history
    async with sessions() as session:
        await session.execute(update(AgentRun).where(AgentRun.workspace_id == root.workspace_id,
                                                     AgentRun.id == second.id).values(
            lease_token=3, lease_expires_at=datetime.now(UTC) + timedelta(minutes=5)))
        await session.commit()
    assert await specialist_history(sessions, workspace_id=root.workspace_id, run_id=second.id, token=3) == first_history
    with pytest.raises(Conflict):
        await specialist_history(sessions, workspace_id=root.workspace_id, run_id=second.id, token=2)
    with pytest.raises(Conflict):
        await specialist_history(sessions, workspace_id=uuid7(), run_id=second.id, token=3)
    # A forged session ID cannot make another person's task read this history.
    async with sessions() as session:
        foreign = await session.get(AgentRun, children[other_owner.id].id)
        foreign.specialist_session_id = ids[0]
        foreign.specialist_history = {"version": 1, "ids": [str(first.id)], "omitted": False}
        foreign.status, foreign.lease_token = RunStatus.RUNNING, 1
        foreign.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        await session.commit()
    with pytest.raises(Forbidden):
        await specialist_history(sessions, workspace_id=root.workspace_id, run_id=foreign.id, token=1)
    resolve = specialist_sessions.AgentDefinitionRepository.resolve

    async def changed_permissions(self, *args, **kwargs):
        definitions = await resolve(self, *args, **kwargs)
        return [replace(item, spec=item.spec.model_copy(update={"tools": []})) if item.spec.handle == "research" else item
                for item in definitions]

    monkeypatch.setattr(specialist_sessions.AgentDefinitionRepository, "resolve", changed_permissions)
    with pytest.raises(Forbidden, match="permissions changed"):
        await specialist_history(sessions, workspace_id=root.workspace_id, run_id=second.id, token=3)
    monkeypatch.setattr(specialist_sessions.AgentDefinitionRepository, "resolve", resolve)
    # A person who still has chat access must not receive history from a more privileged role.
    async with sessions() as session:
        await session.execute(update(Membership).where(Membership.workspace_id == root.workspace_id,
            Membership.user_id == root.requested_by_id).values(role=Role.MEMBER))
        await session.commit()
    with pytest.raises(Forbidden, match="permissions changed"):
        await specialist_history(sessions, workspace_id=root.workspace_id, run_id=second.id, token=3)
    async with sessions() as session:
        await session.execute(update(Membership).where(Membership.workspace_id == root.workspace_id,
            Membership.user_id == root.requested_by_id).values(role=Role.OWNER))
        await session.commit()
    load = specialist_sessions._load_history
    reads = 0

    async def revoke_after_read(*args, **kwargs):
        nonlocal reads
        result = await load(*args, **kwargs)
        reads += 1
        if reads == 1:
            async with sessions() as session:
                await session.execute(update(Membership).where(Membership.workspace_id == root.workspace_id,
                    Membership.user_id == root.requested_by_id).values(role=Role.GUEST))
                await session.commit()
        return result

    monkeypatch.setattr(specialist_sessions, "_load_history", revoke_after_read)
    with pytest.raises(Forbidden):
        await specialist_history(sessions, workspace_id=root.workspace_id, run_id=second.id, token=3)
    monkeypatch.setattr(specialist_sessions, "_load_history", load)
    async with sessions() as session:
        await session.execute(update(Membership).where(Membership.workspace_id == root.workspace_id,
                                                        Membership.user_id == root.requested_by_id).values(role=Role.OWNER))
        await session.execute(delete(AgentSpecialistSession).where(AgentSpecialistSession.workspace_id == root.workspace_id,
                                                                   AgentSpecialistSession.id == ids[0]))
        await session.commit()
    with pytest.raises(Forbidden):
        await specialist_history(sessions, workspace_id=root.workspace_id, run_id=second.id, token=3)


async def test_history_is_bounded_and_fixed_when_a_task_is_queued(nova_pilot_world):
    root, sessions, secrets = nova_pilot_world

    async def dispatch(_run_id, _payload):
        pass

    runner = SimpleNamespace(session_factory=sessions, secrets=secrets, queue=None, stop_reasons=None,
                             settings=SimpleNamespace(specialist_continuity=True), _dispatch=dispatch)
    scheduler = DelegationService(runner)
    await scheduler.submit(root.workspace_id, root.id, 1, "call", _batch("Review the history"))
    async with sessions() as session:
        current = await session.scalar(select(AgentRun).where(AgentRun.workspace_id == root.workspace_id,
                                                               AgentRun.parent_run_id == root.id))
        saved = await session.get(AgentSpecialistSession, current.specialist_session_id)
        history_snapshot = {"version": 1, "ids": [], "omitted": False, "policy": await _current_policy(session, saved)}
        now = datetime.now(UTC)
        previous = []
        for i in range(10):
            item = AgentRun(id=uuid7(), workspace_id=root.workspace_id, project_id=root.project_id,
                            thread_id=uuid7(), parent_run_id=root.id, delegation_key=f"old-{i}", task_key=f"old-{i}",
                            specialist_session_id=current.specialist_session_id, specialist_history=history_snapshot,
                            requested_by_id=root.requested_by_id,
                            source="specialist", agent="research", kind=RunKind.CHAT, status=RunStatus.COMPLETED,
                            message=f"Earlier task {i}", reply=f"Earlier reply {i}",
                            task_result=SpecialistResult(summary=f"<finding {i}>").model_dump(mode="json"),
                            created_at=now, updated_at=now, finished_at=now + timedelta(seconds=i))
            previous.append(item)
            session.add(item)
        for key, status, result_status in [("partial", RunStatus.COMPLETED, "partial"),
                                           ("failed", RunStatus.FAILED, "completed")]:
            session.add(AgentRun(
                id=uuid7(), workspace_id=root.workspace_id, project_id=root.project_id, thread_id=uuid7(),
                parent_run_id=root.id, delegation_key=key, task_key=key,
                specialist_session_id=current.specialist_session_id, specialist_history=history_snapshot,
                requested_by_id=root.requested_by_id,
                source="specialist", agent="research", kind=RunKind.CHAT, status=status,
                message=f"Unfinished {key}", task_result=SpecialistResult(summary=key, status=result_status).model_dump(mode="json"),
                created_at=now, updated_at=now, finished_at=now + timedelta(minutes=2),
            ))
        await session.commit()
    await scheduler.wait(root.workspace_id, root.id, 1, {"interrupt": "call"})
    async with sessions() as session:
        current = await session.get(AgentRun, current.id)
        assert current.specialist_history == {"version": 1, "ids": [str(item.id) for item in previous[2:]], "omitted": True,
                                              "policy": history_snapshot["policy"]}
        current.status, current.lease_token = RunStatus.RUNNING, 1
        current.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        # A later completion cannot change the list chosen for this attempt.
        late = AgentRun(id=uuid7(), workspace_id=root.workspace_id, project_id=root.project_id,
                        thread_id=uuid7(), parent_run_id=root.id, delegation_key="late", task_key="late",
                        specialist_session_id=current.specialist_session_id, specialist_history=history_snapshot,
                        requested_by_id=root.requested_by_id,
                        source="specialist", agent="research", kind=RunKind.CHAT, status=RunStatus.COMPLETED,
                        message="Late finding", task_result=SpecialistResult(summary="Too late").model_dump(mode="json"),
                        created_at=now, updated_at=now, finished_at=now + timedelta(minutes=1))
        session.add(late)
        await session.commit()
    history = await specialist_history(sessions, workspace_id=root.workspace_id, run_id=current.id, token=1)
    assert "Some older specialist work was omitted" in history
    assert "Earlier task 0" not in history and "Earlier task 2" in history
    assert "&lt;finding 9&gt;" in history and "Too late" not in history


async def test_cancelling_a_parent_releases_its_specialist_session(nova_pilot_world):
    root, sessions, secrets = nova_pilot_world
    now = datetime.now(UTC)
    async with sessions() as session:
        other = AgentRun(id=uuid7(), workspace_id=root.workspace_id, project_id=root.project_id,
                         thread_id=root.thread_id, requested_by_id=root.requested_by_id, kind=RunKind.CHAT,
                         status=RunStatus.RUNNING, message="Another question", work_mode=WorkMode.DISCUSS,
                         orchestration=True, lease_token=1, lease_expires_at=now + timedelta(minutes=5),
                         created_at=now, updated_at=now)
        session.add(other)
        await session.commit()
    dispatched = []

    async def dispatch(run_id, payload):
        dispatched.append((run_id, payload))

    async def stop(_run_id, _reason):
        pass

    runner = SimpleNamespace(session_factory=sessions, secrets=secrets, queue=None, stop_reasons=None, stop=stop,
                             settings=SimpleNamespace(specialist_continuity=True), _dispatch=dispatch)
    scheduler = DelegationService(runner)
    for parent in (root, other):
        await scheduler.submit(root.workspace_id, parent.id, 1, "call", _batch("Research"))
        await scheduler.wait(root.workspace_id, parent.id, 1, {"interrupt": "call"})
    async with sessions() as session:
        waiting = await session.scalar(select(AgentRun).where(AgentRun.workspace_id == root.workspace_id,
                                                               AgentRun.parent_run_id == other.id))
        assert waiting.status is RunStatus.WAITING_DEPENDENCY
    await scheduler.cancel(root.workspace_id, root.id, "Stopped")
    async with sessions() as session:
        waiting = await session.get(AgentRun, waiting.id)
        assert waiting.status is RunStatus.QUEUED and waiting.specialist_history["ids"] == []
        assert dispatched[-1][0] == waiting.id


@pytest.mark.parametrize("change", ["none", "role", "specialist", "sealed", "ephemeral"])
async def test_saved_results_are_authorized_at_each_read(nova_pilot_world, monkeypatch, change):
    from dotrix_backend.core.errors import NotFound
    from dotrix_backend.modules.agent_definitions.repository import AgentDefinitionRepository
    from dotrix_backend.modules.agents.service import AgentService
    from dotrix_backend.modules.agents.team_service import TeamService
    from dotrix_backend.modules.projects.deps import ProjectAccess
    from dotrix_backend.modules.workspaces.repository import MembershipRepository

    root, sessions, secrets = nova_pilot_world

    async def dispatch(_run_id, _payload):
        pass

    runner = SimpleNamespace(session_factory=sessions, secrets=secrets, queue=None, stop_reasons=None,
                             settings=SimpleNamespace(specialist_continuity=change != "ephemeral"), _dispatch=dispatch)
    scheduler = DelegationService(runner)
    await scheduler.submit(root.workspace_id, root.id, 1, "call", _batch("Private task evidence"))
    await scheduler.wait(root.workspace_id, root.id, 1, {"interrupt": "call"})
    async with sessions() as session:
        child = await session.scalar(select(AgentRun).where(AgentRun.parent_run_id == root.id))
        child.status, child.finished_at = RunStatus.COMPLETED, datetime.now(UTC)
        child.reply = "Private result evidence"
        child.task_result = SpecialistResult(summary=child.reply).model_dump(mode="json")
        if change == "sealed":
            child.specialist_history = {**child.specialist_history, "policy": None}
        if change in ("role", "ephemeral"):
            await session.execute(update(Membership).where(Membership.workspace_id == root.workspace_id,
                Membership.user_id == root.requested_by_id).values(role=Role.MEMBER))
        parent = await session.get(AgentRun, root.id)
        parent.status = RunStatus.RUNNING
        child_id = child.id
        await session.commit()
    if change == "specialist":
        resolve = AgentDefinitionRepository.resolve

        async def changed(self, *args, **kwargs):
            return [replace(item, spec=item.spec.model_copy(update={"tools": []})) if item.spec.handle == "research" else item
                    for item in await resolve(self, *args, **kwargs)]

        monkeypatch.setattr(AgentDefinitionRepository, "resolve", changed)
    visible = change in ("none", "ephemeral")
    async with sessions() as session:
        member = await MembershipRepository(session).get(root.workspace_id, root.requested_by_id)
        access = ProjectAccess(await session.get(Project, root.project_id), member)
        team = TeamService(session)
        listed = await team.tasks(access, root.id)
        assert len(listed) == 1  # Status remains visible even when the stored content is withheld.
        assert (listed[0].task_result is not None) is visible
        if not visible:
            assert "Private" not in listed[0].model_dump_json()
        activity = await team.activity(member)
        assert any(item.run_id == child_id for item in activity) is visible
        service = AgentService(session, runner)
        if visible:
            assert (await service.get(access, child_id)).reply == "Private result evidence"
            await service.run_events(access, child_id, 0, 100)
            await service.check_run(access, child_id)
        else:
            for read in (service.get(access, child_id), service.run_events(access, child_id, 0, 100), service.check_run(access, child_id)):
                with pytest.raises(NotFound):
                    await read
    result = await scheduler.submit(root.workspace_id, root.id, 1, "call", _batch("Private task evidence"))
    assert (result[0]["result"] is not None) is visible
    if not visible:
        assert "Private" not in str(result)
    if change == "none":
        from dotrix_backend.modules.agents import router

        async def stream(*_args):
            yield "delta", "Before permission change"
            async with sessions() as session:
                await session.execute(update(Membership).where(Membership.workspace_id == root.workspace_id,
                    Membership.user_id == root.requested_by_id).values(role=Role.MEMBER))
                await session.commit()
            yield "delta", "Private result after permission change"

        monkeypatch.setattr(router, "follow_run", stream)
        runner.streams = object()
        async with sessions() as session:
            member = await MembershipRepository(session).get(root.workspace_id, root.requested_by_id)
            access = ProjectAccess(await session.get(Project, root.project_id), member)
            response = await router.stream_run(child_id, access, AgentService(session, runner))
            chunks = [piece async for piece in response.body_iterator]
        body = "".join(piece.decode() if isinstance(piece, bytes) else piece for piece in chunks)
        assert "Before permission change" in body and "Private result after permission change" not in body
        assert "event: end" in body


async def test_only_one_limit_continuation_can_reserve_a_specialist_session(nova_pilot_world):
    from dotrix_backend.modules.agents.service import continue_due_runs, resume_limited
    from dotrix_backend.modules.agents.specialist_sessions import SpecialistSessionBusy
    from dotrix_backend.modules.agents.team_service import TeamService
    from dotrix_backend.modules.projects.deps import ProjectAccess
    from dotrix_backend.modules.workspaces.repository import MembershipRepository

    root, sessions, secrets = nova_pilot_world
    dispatched = []

    async def dispatch(run_id, payload):
        dispatched.append(run_id)

    async def continue_run(run_id, message, **kwargs):
        dispatched.append(run_id)

    runner = SimpleNamespace(session_factory=sessions, secrets=secrets, queue=None, stop_reasons=None,
                             settings=SimpleNamespace(specialist_continuity=True), _dispatch=dispatch,
                             prepare_dispatch=lambda *_args: None, continue_run=continue_run)
    scheduler = DelegationService(runner)
    tasks = _batch("First").tasks + [*_batch("Second").tasks]
    tasks[1] = tasks[1].model_copy(update={"key": "second"})
    await scheduler.submit(root.workspace_id, root.id, 1, "call", SpecialistBatch(tasks=tasks))
    await scheduler.wait(root.workspace_id, root.id, 1, {"interrupt": "call"})
    async with sessions() as session:
        children = list(await session.scalars(select(AgentRun).where(AgentRun.parent_run_id == root.id)))
        member = await MembershipRepository(session).get(root.workspace_id, root.requested_by_id)
        access = ProjectAccess(await session.get(Project, root.project_id), member)
        listed = await TeamService(session).tasks(access, root.id)
        assert len(listed) == 2
        waiting = next(item for item in listed if item.status is RunStatus.WAITING_DEPENDENCY)
        assert waiting.message == "Specialist details are unavailable"
        assert children[0].specialist_session_id == children[1].specialist_session_id
        ids = [child.id for child in children]
        for child in children:
            child.status, child.error_kind = RunStatus.FAILED, "model_limit"
            child.resumes_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    dispatched.clear()

    async def attempt(run_id):
        async with sessions() as session:
            run = await session.get(AgentRun, run_id)
            await resume_limited(session, runner, run)

    results = await asyncio.gather(*(attempt(run_id) for run_id in ids), return_exceptions=True)
    assert results.count(None) == 1 and sum(isinstance(item, SpecialistSessionBusy) for item in results) == 1
    assert len(dispatched) == 1
    async with sessions() as session:
        children = list(await session.scalars(select(AgentRun).where(AgentRun.id.in_(ids))))
        winner = next(child for child in children if child.status is RunStatus.QUEUED)
        loser = next(child for child in children if child.status is RunStatus.FAILED)
        winner_id, loser_id = winner.id, loser.id
        loser.continue_at_reset = True
        await session.commit()
        assert await continue_due_runs(session, runner) == 0
    async with sessions() as session:
        loser = await session.get(AgentRun, loser_id)
        assert loser.continue_at_reset and loser.status is RunStatus.FAILED
        winner = await session.get(AgentRun, winner_id)
        winner.status = RunStatus.COMPLETED
        await session.commit()
        assert await continue_due_runs(session, runner) == 1
    assert len(dispatched) == 2


@pytest.mark.parametrize("change", ["none", "role", "specialist"])
@pytest.mark.parametrize("when", ["before", "after"])
async def test_dependency_handoff_withholds_results_under_changed_permissions(nova_pilot_world, monkeypatch, agent_script, change, when):
    from dotrix_backend.modules.agent_definitions.repository import AgentDefinitionRepository

    root, sessions, secrets = nova_pilot_world

    async def dispatch(_run_id, _payload):
        pass

    runner = AgentRunner(session_factory=sessions, secrets=secrets, checkpointer=InMemorySaver(),
                         model_factory=agent_script.factory, inline=True,
                         settings=SimpleNamespace(specialist_continuity=True, agent_lease_seconds=300))
    monkeypatch.setattr(runner, "_dispatch", dispatch)
    scheduler = DelegationService(runner)
    batch = SpecialistBatch(tasks=[
        {"key": "research", "agent": "research", "brief": "Investigate", "expected_result": "Evidence"},
        {"key": "docs", "agent": "documentation", "brief": "Summarize", "expected_result": "Summary", "depends_on": ["research"]},
    ])
    await scheduler.submit(root.workspace_id, root.id, 1, "call", batch)
    await scheduler.wait(root.workspace_id, root.id, 1, {"interrupt": "call"})
    async with sessions() as session:
        source = await session.scalar(select(AgentRun).where(AgentRun.parent_run_id == root.id, AgentRun.task_key == "research"))
        source.status, source.finished_at = RunStatus.COMPLETED, datetime.now(UTC)
        source.task_result = SpecialistResult(summary="Private dependency evidence").model_dump(mode="json")
        await session.commit()
    if when == "after":
        await scheduler.advance(root.workspace_id, root.id)
    if change == "role":
        async with sessions() as session:
            await session.execute(update(Membership).where(Membership.workspace_id == root.workspace_id,
                Membership.user_id == root.requested_by_id).values(role=Role.MEMBER))
            await session.commit()
    if change == "specialist":
        resolve = AgentDefinitionRepository.resolve

        async def changed(self, *args, **kwargs):
            return [replace(item, spec=item.spec.model_copy(update={"tools": []})) if item.spec.handle == "research" else item
                    for item in await resolve(self, *args, **kwargs)]

        monkeypatch.setattr(AgentDefinitionRepository, "resolve", changed)
    await scheduler.advance(root.workspace_id, root.id)
    async with sessions() as session:
        dependent = await session.scalar(select(AgentRun).where(AgentRun.parent_run_id == root.id, AgentRun.task_key == "docs"))
        assert dependent.status is (RunStatus.QUEUED if change == "none" or when == "after" else RunStatus.BLOCKED)
        assert ("Private dependency evidence" in dependent.message) is (change == "none" or when == "after")
        from dotrix_backend.modules.agents.specialist_sessions import specialist_result_visible

        assert await specialist_result_visible(session, dependent) is (change == "none")
        dependent_id, message = dependent.id, dependent.message
    if when == "after" and change == "none":
        async with sessions() as session:
            dependent = await session.get(AgentRun, dependent_id)
            dependent.status, dependent.finished_at = RunStatus.COMPLETED, datetime.now(UTC)
            dependent.task_result = SpecialistResult(summary="Private derived evidence").model_dump(mode="json")
            historical = AgentRun(
                id=uuid7(), workspace_id=root.workspace_id, project_id=root.project_id, parent_run_id=root.id,
                thread_id=uuid7(), requested_by_id=root.requested_by_id, source="specialist", agent="documentation",
                specialist_session_id=dependent.specialist_session_id,
                specialist_history={**dependent.specialist_history, "ids": [str(dependent.id)]},
                task_key="history", delegation_key="history", depends_on=[], kind=RunKind.CHAT,
                status=RunStatus.COMPLETED, message="Later task", reply="Private derived evidence",
                task_result=SpecialistResult(summary="Private derived evidence").model_dump(mode="json"),
                created_at=datetime.now(UTC), updated_at=datetime.now(UTC), finished_at=datetime.now(UTC),
            )
            session.add(historical)
            await session.commit()
            assert await specialist_result_visible(session, historical)
        resolve = AgentDefinitionRepository.resolve

        async def revoked(self, *args, **kwargs):
            return [replace(item, spec=item.spec.model_copy(update={"tools": []})) if item.spec.handle == "research" else item
                    for item in await resolve(self, *args, **kwargs)]

        monkeypatch.setattr(AgentDefinitionRepository, "resolve", revoked)
        async with sessions() as session:
            historical = await session.get(AgentRun, historical.id)
            assert not await specialist_result_visible(session, historical)
    if when == "after" and change != "none":
        model = agent_script.say("This must not run")
        await runner.execute(dependent_id, {"kind": "start", "message": message})
        assert not model.received
        async with sessions() as session:
            dependent = await session.get(AgentRun, dependent_id)
            assert dependent.status is RunStatus.FAILED and dependent.task_result is None


async def test_a_permission_change_during_work_excludes_the_result_from_later_history(
    nova_pilot_world, agent_script,
):
    root, sessions, secrets = nova_pilot_world
    settings = SimpleNamespace(specialist_continuity=True)
    runner = AgentRunner(session_factory=sessions, checkpointer=InMemorySaver(), model_factory=agent_script.factory,
                         inline=True, secrets=secrets, settings=settings)

    async def dispatch(_run_id, _payload):
        pass

    runner._dispatch = dispatch
    scheduler = DelegationService(runner)
    await scheduler.submit(root.workspace_id, root.id, 1, "call", _batch("Investigate"))
    await scheduler.wait(root.workspace_id, root.id, 1, {"interrupt": "call"})
    async with sessions() as session:
        child = await session.scalar(select(AgentRun).where(AgentRun.workspace_id == root.workspace_id,
                                                             AgentRun.parent_run_id == root.id))
        child.status, child.lease_token = RunStatus.RUNNING, 1
        child.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        await session.execute(update(Membership).where(Membership.workspace_id == root.workspace_id,
            Membership.user_id == root.requested_by_id).values(role=Role.MEMBER))
        await session.commit()
    lease = _LEASE.set(1)
    try:
        await runner._finish(child.id, {"messages": [AIMessage(content="Finished")]}, TokenUsage(), speaker="research",
                             specialist_result=SpecialistResult(summary="Sensitive finding").model_dump(mode="json"))
    finally:
        _LEASE.reset(lease)
    async with sessions() as session:
        saved = await session.get(AgentRun, child.id)
        assert saved.status is RunStatus.COMPLETED and saved.specialist_history["policy"] is None
        await session.execute(update(Membership).where(Membership.workspace_id == root.workspace_id,
            Membership.user_id == root.requested_by_id).values(role=Role.OWNER))
        now = datetime.now(UTC)
        later = AgentRun(id=uuid7(), workspace_id=root.workspace_id, project_id=root.project_id,
                         thread_id=root.thread_id, requested_by_id=root.requested_by_id, kind=RunKind.CHAT,
                         status=RunStatus.RUNNING, message="Follow up", work_mode=WorkMode.DISCUSS,
                         orchestration=True, lease_token=1, lease_expires_at=now + timedelta(minutes=5),
                         created_at=now, updated_at=now)
        session.add(later)
        await session.commit()
    await scheduler.submit(root.workspace_id, later.id, 1, "later", _batch("Follow up"))
    await scheduler.wait(root.workspace_id, later.id, 1, {"interrupt": "later"})
    async with sessions() as session:
        follow_up = await session.scalar(select(AgentRun).where(AgentRun.workspace_id == root.workspace_id,
                                                                 AgentRun.parent_run_id == later.id))
        assert follow_up.status is RunStatus.QUEUED and follow_up.specialist_history["ids"] == []


@pytest.mark.parametrize("continuation", ["continue", "resume", "recovered_start", "approval"])
@pytest.mark.parametrize("change", ["none", "role", "specialist", "access", "project_access", "early_error"])
async def test_checkpoint_continuation_revalidates_specialist_history(
    nova_pilot_world, agent_script, monkeypatch, continuation, change,
):
    """A checkpoint must not expose old history under a different permission policy."""
    from dotrix_backend.modules.agent_definitions.repository import AgentDefinitionRepository
    from dotrix_backend.modules.agents import runner as runner_module

    class LimitedModel(ScriptedChatModel):
        def _generate(self, messages, *args, **kwargs):
            if not self.received:
                return super()._generate(messages, *args, **kwargs)
            self.received.append(list(messages))
            raise RuntimeError("429 rate limit: try again in 30 seconds")

    root, sessions, secrets = nova_pilot_world
    if change == "project_access":
        async with sessions() as session:
            await session.execute(update(Membership).where(Membership.workspace_id == root.workspace_id,
                Membership.user_id == root.requested_by_id).values(role=Role.MEMBER))
            await session.commit()
    settings = SimpleNamespace(specialist_continuity=True, agent_lease_seconds=300)
    runner = AgentRunner(session_factory=sessions, checkpointer=InMemorySaver(), model_factory=agent_script.factory,
                         inline=True, secrets=secrets, settings=settings)

    async def dispatch(_run_id, _payload):
        pass

    monkeypatch.setattr(runner, "_dispatch", dispatch)
    scheduler = DelegationService(runner)
    await scheduler.submit(root.workspace_id, root.id, 1, "first", _batch("Earlier investigation"))
    await scheduler.wait(root.workspace_id, root.id, 1, {"interrupt": "first"})
    now = datetime.now(UTC)
    async with sessions() as session:
        prior = await session.scalar(select(AgentRun).where(AgentRun.parent_run_id == root.id))
        prior.status, prior.finished_at = RunStatus.COMPLETED, now
        prior.task_result = SpecialistResult(summary="Private prior finding").model_dump(mode="json")
        prior.reply = "Earlier work finished."
        later = AgentRun(id=uuid7(), workspace_id=root.workspace_id, project_id=root.project_id,
                         thread_id=root.thread_id, requested_by_id=root.requested_by_id, kind=RunKind.CHAT,
                         status=RunStatus.RUNNING, message="Follow up", work_mode=WorkMode.DISCUSS,
                         orchestration=True, lease_token=1, lease_expires_at=now + timedelta(minutes=5),
                         created_at=now, updated_at=now)
        session.add(later)
        await session.commit()
    await scheduler.submit(root.workspace_id, later.id, 1, "second", _batch("Check earlier work"))
    await scheduler.wait(root.workspace_id, later.id, 1, {"interrupt": "second"})
    async with sessions() as session:
        child = await session.scalar(select(AgentRun).where(AgentRun.parent_run_id == later.id))
        assert child.specialist_history["ids"] == [str(prior.id)]
        child_id, message = child.id, child.message
    limited = LimitedModel.of(tool_call("submit_specialist_result", summary="Private prior finding"))
    if continuation == "approval":
        # Current read-only specialists disable pipeline checkpoints; preserve the pipeline
        # here to exercise a real previously paused checkpoint if that configuration changes.
        read_only = runner_module.read_only
        monkeypatch.setattr(runner_module, "read_only", lambda spec: read_only(spec).model_copy(update={"pipeline": spec.pipeline}))
        initial = agent_script.say(tool_call("submit_specialist_result", summary="Private prior finding"),
                                   tool_call("checkpoint", summary="A research plan", plan=["Check sources"]))
    else:
        initial = agent_script.model = limited
    await runner.execute(child_id, {"kind": "start", "message": message})
    async with sessions() as session:
        child = await session.get(AgentRun, child_id)
        if continuation == "approval":
            assert child.status is RunStatus.AWAITING_APPROVAL, child.error
            approval = await session.scalar(select(AgentApproval).where(AgentApproval.run_id == child_id))
            assert approval and approval.tool == "checkpoint" and child.task_result["summary"] == "Private prior finding"
            interrupt_id = approval.interrupt_id
        else:
            assert child.status is RunStatus.FAILED and child.error_kind == "model_limit", child.error
            assert child.task_result["summary"] == "Private prior finding"  # an ordinary limit retains it
        assert any("Private prior finding" in str(msg.content) for msg in initial.received[0])
        child.status, child.error, child.error_kind = RunStatus.QUEUED, None, None
        if change in ("role", "access", "early_error"):
            await session.execute(update(Membership).where(Membership.workspace_id == root.workspace_id,
                Membership.user_id == root.requested_by_id).values(role=Role.GUEST if change == "access" else Role.MEMBER))
        if change == "project_access":
            await session.execute(update(Project).where(Project.id == root.project_id).values(access=ProjectAccessLevel.RESTRICTED))
        await session.commit()
    if change == "specialist":
        resolve = AgentDefinitionRepository.resolve

        async def changed_permissions(self, *args, **kwargs):
            definitions = await resolve(self, *args, **kwargs)
            return [replace(item, spec=item.spec.model_copy(update={"tools": []})) if item.spec.handle == "research" else item
                    for item in definitions]

        monkeypatch.setattr(AgentDefinitionRepository, "resolve", changed_permissions)
    model = agent_script.say(tool_call("submit_specialist_result", summary="Checked"), "Done.")
    if change == "early_error":
        from dotrix_backend.modules.agents.llm import ModelUnavailable

        def unavailable(*_args, **_kwargs):
            raise ModelUnavailable("The specialist's provider key is unavailable")

        monkeypatch.setattr(runner, "model_factory", unavailable)
    if continuation == "approval":
        payload = {"kind": "resume", "interrupt_ids": [interrupt_id], "decisions": [["approve", None]]}
    elif continuation == "resume":
        payload = {"kind": "resume", "interrupt_ids": [], "decisions": [], "recovered": True}
    elif continuation == "recovered_start":
        payload = {"kind": "start", "message": message, "recovered": True}
    else:
        payload = {"kind": "continue", "message": message}
    await runner.execute(child_id, payload)
    async with sessions() as session:
        child = await session.get(AgentRun, child_id)
        if change == "none":
            assert child.status is RunStatus.COMPLETED, child.error
            assert model.received
            history = [str(msg.content) for msg in model.received[0] if getattr(msg, "type", None) == "human"]
            assert sum(text.count("Private prior finding") for text in history) == 1
        else:
            assert child.status is RunStatus.FAILED
            expected = ("no longer sees" if change in ("access", "project_access") else
                        "provider key is unavailable" if change == "early_error" else "permissions changed")
            assert expected in child.error
            assert child.task_result is None
            assert not model.received
            if change not in ("access", "project_access"):
                parent = await session.get(AgentRun, later.id)
                assert parent.status is RunStatus.QUEUED
                parent.status, parent.lease_token = RunStatus.RUNNING, 1
                await session.commit()
    if change not in ("none", "access", "project_access"):
        returned = await scheduler.submit(root.workspace_id, later.id, 1, "second", _batch("Check earlier work"))
        assert returned[0]["status"] == "failed" and returned[0]["result"] is None
    if change == "none" and continuation == "recovered_start":
        calls = len(model.received)
        async with sessions() as session:
            child = await session.get(AgentRun, child_id)
            child.status, child.reply = RunStatus.RUNNING, None  # outcome lost after graph completion
            await session.commit()
        await runner.execute(child_id, payload)
        async with sessions() as session:
            child = await session.get(AgentRun, child_id)
            assert child.status is RunStatus.COMPLETED and child.reply == "Done."
        assert len(model.received) == calls  # neither the model nor the history was sent again


async def test_fx_nova_reuses_a_specialists_completed_work_in_the_same_conversation(
    nova_pilot_world, db_client, monkeypatch, agent_script, outbox, storage, checkouts,
):
    from dotrix_engine.runtimes.fx import _HOST

    if not (_HOST / "node_modules" / "libfx").is_dir():
        pytest.skip("Install the optional fx host to exercise the real libfx runtime")
    existing, sessions, secrets = nova_pilot_world
    settings = db_client._transport.app.state.settings.model_copy(update={
        "fx_chat_durable_delegation": True, "specialist_continuity": True,
    })
    async with sessions() as session:
        await session.execute(update(Project).where(Project.id == existing.project_id).values(
            specialist_model="openai:cheap-model"))
        await session.commit()
    app = create_app(settings)
    app.state.sessionmaker, app.state.secrets, app.state.checkouts = sessions, secrets, checkouts
    app.dependency_overrides[get_email_sender] = lambda: outbox
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[optional_storage] = lambda: storage
    app.state.runner = runner = AgentRunner(
        session_factory=sessions, checkpointer=InMemorySaver(), model_factory=agent_script.factory,
        inline=True, checkouts=checkouts, secrets=secrets, settings=settings,
    )
    app.state.jobs = InlineJobs(JobContext(sessions, settings, outbox, storage, checkouts=checkouts, runner=runner), JOBS)
    runner.jobs = app.state.jobs
    model = agent_script.say(
        tool_call("submit_specialist_result", summary="Earlier architecture finding: use PostgreSQL"), "First work complete.",
        tool_call("submit_specialist_result", summary="The earlier finding still applies"), "Second work complete.",
    )
    token = create_access_token(existing.requested_by_id, secret=settings.jwt_secret.get_secret_value(),
                                issuer=settings.jwt_issuer, ttl=timedelta(minutes=10))
    headers = {"Authorization": f"Bearer {token}"}
    base = f"/v1/workspaces/{existing.workspace_id}/projects/{existing.project_id}/agent"
    args = {"tasks": [{"key": "research", "agent": "research", "brief": "Investigate the data store",
                       "expected_result": "Recommendation"}]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with model_server(tool_name="delegate_tasks", tool_args=args) as url:
            monkeypatch.setitem(fx_pilot._FX_ENDPOINTS, "openai", url)
            first = await client.post(f"{base}/runs", headers=headers, json={
                "message": "Investigate the data store", "chat_runtime": "fx", "work_mode": "discuss",
            })
            assert first.status_code == 202 and first.json()["status"] == "completed", first.text
            args["tasks"][0]["brief"] = "Check the earlier recommendation"
            second = await client.post(f"{base}/runs", headers=headers, json={
                "message": "Check that recommendation", "thread_id": first.json()["thread_id"],
                "chat_runtime": "fx", "work_mode": "discuss",
            })
            assert second.status_code == 202 and second.json()["status"] == "completed", second.text
        first_children = (await client.get(f"{base}/runs/{first.json()['id']}/tasks", headers=headers)).json()
        second_children = (await client.get(f"{base}/runs/{second.json()['id']}/tasks", headers=headers)).json()
        async with sessions() as session:
            child1 = await session.get(AgentRun, uuid.UUID(first_children[0]["id"]))
            child2 = await session.get(AgentRun, uuid.UUID(second_children[0]["id"]))
            assert child1.specialist_session_id == child2.specialist_session_id
            assert child1.thread_id != child2.thread_id  # task checkpoints remain isolated
            assert child2.specialist_history["ids"] == [str(child1.id)]
        follow_up = next(messages for messages in model.received if "Check the earlier recommendation" in str(messages[-1].content))
        assert "Earlier architecture finding: use PostgreSQL" in str(follow_up[-1].content)
        assert "openai:cheap-model" in agent_script.models_used


async def test_deepagents_nova_also_reuses_the_specialists_completed_work(
    nova_pilot_world, db_client, agent_script, outbox, storage, checkouts,
):
    existing, sessions, secrets = nova_pilot_world
    settings = db_client._transport.app.state.settings.model_copy(update={
        "durable_delegation": True, "specialist_continuity": True,
    })
    app = create_app(settings)
    app.state.sessionmaker, app.state.secrets, app.state.checkouts = sessions, secrets, checkouts
    app.dependency_overrides[get_email_sender] = lambda: outbox
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[optional_storage] = lambda: storage
    app.state.runner = runner = AgentRunner(
        session_factory=sessions, checkpointer=InMemorySaver(), model_factory=agent_script.factory,
        inline=True, checkouts=checkouts, secrets=secrets, settings=settings,
    )
    app.state.jobs = InlineJobs(JobContext(sessions, settings, outbox, storage, checkouts=checkouts, runner=runner), JOBS)
    runner.jobs = app.state.jobs
    model = agent_script.say(
        tool_call("delegate_tasks", tasks=_batch("Investigate architecture", "architecture").model_dump()["tasks"]),
        tool_call("submit_specialist_result", summary="Prior architecture finding: isolate the gateway"),
        "First review complete.", "Here is the first answer.",
        tool_call("delegate_tasks", tasks=_batch("Revisit the earlier decision", "architecture").model_dump()["tasks"]),
        tool_call("submit_specialist_result", summary="That earlier choice remains sound"),
        "Second review complete.", "Here is the follow-up answer.",
    )
    token = create_access_token(existing.requested_by_id, secret=settings.jwt_secret.get_secret_value(),
                                issuer=settings.jwt_issuer, ttl=timedelta(minutes=10))
    headers = {"Authorization": f"Bearer {token}"}
    base = f"/v1/workspaces/{existing.workspace_id}/projects/{existing.project_id}/agent"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(f"{base}/runs", headers=headers, json={
            "message": "Investigate architecture", "work_mode": "discuss",
        })
        assert first.status_code == 202 and first.json()["status"] == "completed", first.text
        second = await client.post(f"{base}/runs", headers=headers, json={
            "message": "Revisit the architecture", "thread_id": first.json()["thread_id"], "work_mode": "discuss",
        })
        assert second.status_code == 202 and second.json()["status"] == "completed", second.text
    follow_up = next(messages for messages in model.received if "Revisit the earlier decision" in str(messages[-1].content))
    assert "Prior architecture finding: isolate the gateway" in str(follow_up[-1].content)
