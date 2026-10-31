"""Durable delegation exercises real database transitions and checkpoint resumption."""
import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from uuid_utils.compat import uuid7

from dotrix_backend.core.errors import Conflict
from dotrix_backend.modules.agents.delegation import DelegationService
from dotrix_backend.modules.agents.models import AgentRun, RunKind, RunStatus, WorkMode
from dotrix_backend.modules.coding.models import CodingAgent, CodingRun, CodingRunStatus
from dotrix_backend.modules.workspaces.models import Membership, Role
from dotrix_engine.delegation import SpecialistBatch, SpecialistResult
from dotrix_engine.testing import tool_call


@pytest.fixture
async def nova_world(signup, create_team, db_client):
    person = await signup()
    workspace = await create_team(person.headers)
    url = f"/v1/workspaces/{workspace['id']}"
    project = (await db_client.post(f"{url}/projects", json={"key": "NVA", "name": "Nova"}, headers=person.headers)).json()
    return person, workspace, project, url, f"{url}/projects/{project['id']}"


def batch(*keys):
    return SpecialistBatch(tasks=[{"key": key, "agent": "research", "brief": f"Investigate {key}",
                                  "expected_result": "Evidence", "depends_on": ["a"] if key == "d" else []}
                                 for key in keys])


async def parent_run(db_session, world):
    person, workspace, project, _, _ = world
    now = datetime.now(UTC)
    root = AgentRun(id=uuid7(), workspace_id=uuid.UUID(workspace["id"]), project_id=uuid.UUID(project["id"]),
                    thread_id=uuid7(), kind=RunKind.CHAT, status=RunStatus.RUNNING,
                    requested_by_id=uuid.UUID(person.id), message="Research this", work_mode=WorkMode.DISCUSS,
                    orchestration=True, lease_token=1, created_at=now, updated_at=now)
    db_session.add(root)
    await db_session.commit()
    return root


async def test_fixed_roster_and_nova_handles_specialist_mentions(nova_world, db_client, agent_script):
    person, _, _, url, base = nova_world
    roster = (await db_client.get(f"{url}/agent-team", headers=person.headers)).json()
    assert [agent["name"] for agent in roster] == ["Nova", "Lyra", "Orion", "Vega", "Juno", "Echo", "Kai"]
    model = agent_script.say("I can advise on that.")
    response = await db_client.post(f"{base}/agent/runs", headers=person.headers,
                                    json={"message": "What should we consider?", "agent": "research"})
    assert response.status_code == 202, response.text
    assert response.json()["agent"] == "auto" and response.json()["work_mode"] == "discuss"
    assert "You are Nova" in str(model.received[0][0].content)
    assert "involve research" in str(model.received[0][-1].content)


async def test_kai_guidance_is_protected_layered_and_versioned(nova_world, db_client, db_session, signup, add_member):
    from dotrix_backend.modules.coding.brief import build_brief
    from dotrix_backend.modules.issues.service import IssueService
    from dotrix_backend.modules.projects.models import Project

    person, workspace, project_data, url, base = nova_world
    workspace_kai = (await db_client.get(f"{url}/agents/coding-agent", headers=person.headers)).json()
    workspace_kai["additional_instructions"] = "Workspace: use small patches."
    saved = await db_client.put(f"{url}/agents/coding-agent", headers=person.headers, json={"agent": workspace_kai})
    assert saved.status_code == 200, saved.text
    project_kai = (await db_client.get(f"{base}/agents/coding-agent", headers=person.headers)).json()
    project_kai["additional_instructions"] = "Project: add regression coverage."
    saved = await db_client.put(f"{base}/agents/coding-agent", headers=person.headers, json={"agent": project_kai})
    assert saved.status_code == 200, saved.text
    preference = f"{url}/my-agents/coding-agent"
    response = await db_client.put(preference, headers=person.headers, json={"instructions": "Personal: explain tradeoffs."})
    assert response.status_code == 200 and response.json()["version"] == 1
    roster = (await db_client.get(f"{url}/agent-team", headers=person.headers)).json()
    assert next(agent for agent in roster if agent["name"] == "Kai")["customised"]
    issue = (await db_client.post(f"{base}/issues", headers=person.headers, json={"type": "task", "title": "Improve UI"})).json()
    project = await db_session.get(Project, uuid.UUID(project_data["id"]))
    brief = await build_brief(db_session, project, await IssueService(db_session).get(project, issue["key"]),
                              "Implement this", user_id=uuid.UUID(person.id))
    assert brief.index("You are Kai") < brief.index("Workspace: use small patches.")
    assert brief.index("Workspace: use small patches.") < brief.index("Project: add regression coverage.")
    assert brief.index("Project: add regression coverage.") < brief.index("Personal: explain tradeoffs.")
    assert "Don't commit, push, or open a pull request" in brief
    changed = dict(workspace_kai, instructions="Replace protected instructions")
    assert (await db_client.put(f"{url}/agents/coding-agent", headers=person.headers,
                                json={"agent": changed, "base_version": 1})).status_code == 422
    assert (await db_client.delete(preference, headers=person.headers)).status_code == 204
    response = await db_client.put(preference, headers=person.headers, json={"instructions": "Revised preference."})
    assert response.json()["version"] == 3
    history = (await db_client.get(f"{preference}/versions", headers=person.headers)).json()
    assert [(row["version"], row["instructions"]) for row in history] == [
        (3, "Revised preference."), (2, ""), (1, "Personal: explain tradeoffs.")]
    colleague = await signup(email="colleague@example.com")
    await add_member(workspace["id"], colleague.id, Role.MEMBER)
    assert (await db_client.get(f"{preference}/versions", headers=colleague.headers)).json() == []
    audit = (await db_client.get(f"{url}/audit", headers=person.headers, params={"action": "agent_preference.updated"})).json()
    assert len(audit) == 3 and "Personal: explain tradeoffs." not in str(audit)


async def test_permission_revocation_fails_child_and_wakes_parent(nova_world, db_client, db_session, monkeypatch):
    from dotrix_backend.modules.agents.runner import _LEASE

    root = await parent_run(db_session, nova_world)
    runner = db_client._transport.app.state.runner
    service = DelegationService(runner)
    await service.submit(root.workspace_id, root.id, 1, "batch", batch("a"))
    task = await db_session.scalar(select(AgentRun).where(AgentRun.parent_run_id == root.id))
    root.status, root.waiting_interrupts, task.status = RunStatus.WAITING_CHILDREN, {"interrupt": "batch"}, RunStatus.QUEUED
    member = await db_session.scalar(select(Membership).where(Membership.workspace_id == root.workspace_id,
                                                               Membership.user_id == root.requested_by_id))
    member.role = Role.GUEST
    await db_session.commit()
    dispatches = []

    async def dispatch(run_id, payload):
        dispatches.append((run_id, payload))

    monkeypatch.setattr(runner, "_dispatch", dispatch)
    _LEASE.set(999)  # An inline child inherits its parent's context, not its fencing token.
    await runner.execute(task.id, {"kind": "start", "message": task.message})
    await db_session.refresh(task)
    await db_session.refresh(root)
    assert task.status is RunStatus.FAILED and "no longer sees" in task.error
    assert root.status is RunStatus.QUEUED and dispatches[0][0] == root.id


async def test_checkpointed_child_result_returns_to_nova(nova_world, db_client, agent_script, db_session):
    person, _, _, _, base = nova_world
    model = agent_script.say(
        tool_call("delegate_tasks", tasks=batch("a").model_dump()["tasks"]),
        tool_call("submit_specialist_result", summary="Evidence from the project", evidence=["project.md:1"]),
        "Research complete.", "Here is the combined answer.",
    )
    response = await db_client.post(f"{base}/agent/runs", headers=person.headers,
                                    json={"message": "Research the project", "work_mode": "discuss"})
    assert response.status_code == 202, response.text
    root = response.json()
    assert root["status"] == "completed", root
    assert root["reply"] == "Here is the combined answer."
    tasks = (await db_client.get(f"{base}/agent/runs/{root['id']}/tasks", headers=person.headers)).json()
    assert len(tasks) == 1 and tasks[0]["task_result"]["evidence"] == ["project.md:1"]
    child = await db_session.get(AgentRun, uuid.UUID(tasks[0]["id"]))
    assert str(child.thread_id) != root["thread_id"]
    listed = (await db_client.get(f"{base}/agent/runs", headers=person.headers)).json()
    assert [run["id"] for run in listed] == [root["id"]]
    assert len(model.received) == 4


async def test_specialist_models_are_pinned_before_settings_change(nova_world, db_client, agent_script, db_session, monkeypatch):
    from dotrix_backend.modules.agent_definitions.models import AgentPreference
    from dotrix_backend.modules.projects.models import Project

    root = await parent_run(db_session, nova_world)
    project = await db_session.get(Project, root.project_id)
    project.specialist_model = "openai:routine"
    root.conversation_model = "openai:coordinator"
    preference = AgentPreference(workspace_id=root.workspace_id, user_id=root.requested_by_id,
                                 handle="research", model="openai:strong")
    db_session.add(preference)
    await db_session.commit()
    runner = db_client._transport.app.state.runner
    scheduler = DelegationService(runner)
    tasks = SpecialistBatch(tasks=[
        {"key": "product", "agent": "product", "brief": "Summarise", "expected_result": "Summary"},
        {"key": "research", "agent": "research", "brief": "Review", "expected_result": "Evidence"},
    ])
    await scheduler.submit(root.workspace_id, root.id, 1, "batch", tasks)
    children = list(await db_session.scalars(select(AgentRun).where(
        AgentRun.workspace_id == root.workspace_id, AgentRun.parent_run_id == root.id).order_by(AgentRun.task_key)))
    assert {child.agent: child.model for child in children} == {"product": "openai:routine", "research": "openai:strong"}
    project.specialist_model, preference.model = "openai:new-routine", "openai:new-strong"
    root.status, root.waiting_interrupts = RunStatus.WAITING_CHILDREN, {"interrupt": "batch"}
    for child in children:
        child.status = RunStatus.QUEUED
    await db_session.commit()
    agent_script.say(tool_call("submit_specialist_result", summary="Summary"), "Done.",
                     tool_call("submit_specialist_result", summary="Evidence"), "Done.")

    async def dispatch(_run_id, _payload):
        pass

    monkeypatch.setattr(runner, "_dispatch", dispatch)
    for child in children:
        await runner.execute(child.id, {"kind": "start", "message": child.message})
        await db_session.refresh(child)
        assert child.status is RunStatus.COMPLETED
    assert "openai:routine" in agent_script.models_used and "openai:strong" in agent_script.models_used
    assert "openai:new-routine" not in agent_script.models_used and "openai:new-strong" not in agent_script.models_used


async def test_pinned_specialist_does_not_require_new_project_model_key(nova_world, db_client, agent_script, db_session, monkeypatch):
    from dotrix_backend.modules.agents import llm
    from dotrix_backend.modules.agents import runner as runner_module
    from dotrix_backend.modules.projects.models import Project

    root = await parent_run(db_session, nova_world)
    project = await db_session.get(Project, root.project_id)
    project.specialist_model = "openai:original"
    await db_session.commit()
    runner = db_client._transport.app.state.runner
    await DelegationService(runner).submit(root.workspace_id, root.id, 1, "batch", batch("a"))
    child = await db_session.scalar(select(AgentRun).where(AgentRun.parent_run_id == root.id))
    assert child.model == "openai:original"
    project.specialist_model = "google_genai:changed"
    root.status, root.waiting_interrupts, child.status = RunStatus.WAITING_CHILDREN, {"interrupt": "batch"}, RunStatus.QUEUED
    await db_session.commit()
    model = agent_script.say(tool_call("submit_specialist_result", summary="Evidence"), "Done.")
    built = []

    async def keys(*_args, **_kwargs):
        return SimpleNamespace(keys={"openai": "personal-key"})

    def build(name, key, **_):
        built.append((name, key))
        return model

    async def dispatch(_run_id, _payload):
        pass

    monkeypatch.setattr(runner_module, "run_keys", keys)
    monkeypatch.setattr(llm, "build_chat_model", build)
    monkeypatch.setattr(runner, "model_factory", llm.settings_model_factory(runner.settings))
    monkeypatch.setattr(runner, "_dispatch", dispatch)
    await runner.execute(child.id, {"kind": "start", "message": child.message})
    await db_session.refresh(child)
    assert child.status is RunStatus.COMPLETED, child.error
    assert built == [("openai:original", "personal-key")]


async def test_two_children_overlap_third_waits_and_completed_results_are_reused(nova_world, db_session):
    root = await parent_run(db_session, nova_world)
    started = []
    both_started = asyncio.Event()

    @asynccontextmanager
    async def sessions():
        yield db_session

    async def dispatch(run_id, payload):
        started.append((run_id, payload))
        if len(started) >= 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), 2)

    runner = SimpleNamespace(session_factory=sessions, queue=None, stop_reasons=None, _dispatch=dispatch)
    service = DelegationService(runner)
    assert await service.submit(root.workspace_id, root.id, 1, "batch", batch("a", "b", "c", "d")) is None
    assert await service.submit(root.workspace_id, root.id, 1, "batch", batch("a", "b", "c", "d")) is None
    await service.wait(root.workspace_id, root.id, 1, {"interrupt": "batch"})
    assert len(started) == 2  # This would deadlock if publication ran children sequentially.
    tasks = list(await db_session.scalars(select(AgentRun).where(AgentRun.parent_run_id == root.id).order_by(AgentRun.task_key)))
    a, b, c, d = tasks
    assert a.status is b.status is RunStatus.QUEUED
    assert c.status is d.status is RunStatus.WAITING_DEPENDENCY
    a.status, a.task_result = RunStatus.COMPLETED, SpecialistResult(summary="A's saved result").model_dump()
    await db_session.commit()
    await DelegationService(runner).advance(root.workspace_id, root.id)
    assert len(started) == 3 and started[-1][0] == c.id
    await DelegationService(runner).advance(root.workspace_id, root.id)
    assert len(started) == 3
    for task in (b, c):
        task.status, task.task_result = RunStatus.COMPLETED, SpecialistResult(summary="Done").model_dump()
    await db_session.commit()
    await service.advance(root.workspace_id, root.id)
    assert len(started) == 4 and started[-1][0] == d.id
    assert "saved result" in d.message and '<data source="dependencies">' in d.message
    d.status, d.task_result = RunStatus.COMPLETED, SpecialistResult(summary="Done").model_dump()
    await db_session.commit()
    await service.advance(root.workspace_id, root.id)
    await service.advance(root.workspace_id, root.id)
    assert len(started) == 5 and started[-1][1]["kind"] == "delegation_ready"


async def test_private_child_activity_and_cancellation(nova_world, db_client, db_session, signup):
    person, _, _, url, base = nova_world
    root = await parent_run(db_session, nova_world)

    @asynccontextmanager
    async def sessions():
        yield db_session

    stopped = []

    async def stop(run_id, reason):
        stopped.append(run_id)

    service = DelegationService(SimpleNamespace(session_factory=sessions, stop=stop))
    await service.submit(root.workspace_id, root.id, 1, "batch", batch("a"))
    stranger = await signup(email="stranger@example.com")
    hidden = await db_client.get(f"{base}/agent/runs/{root.id}/tasks", headers=stranger.headers)
    assert hidden.status_code == 404
    activity = (await db_client.get(f"{url}/agent/activity", headers=person.headers)).json()
    assert any(row["parent_run_id"] == str(root.id) and row["thread_id"] == str(root.thread_id) for row in activity)
    await service.cancel(root.workspace_id, root.id, "Stopped by the requester")
    rows = list(await db_session.scalars(select(AgentRun).where((AgentRun.id == root.id) | (AgentRun.parent_run_id == root.id))))
    assert len(stopped) == 2 and all(row.status is RunStatus.CANCELLED for row in rows)
    with pytest.raises(Conflict):
        await service.submit(root.workspace_id, root.id, 1, "batch", batch("a"))


@pytest.mark.parametrize("status", [CodingRunStatus.PR_OPENED, CodingRunStatus.FAILED])
async def test_coding_outcomes_and_juno_return_once_to_original_chat(nova_world, db_client, db_session, agent_script, status):
    from dotrix_backend.modules.agents.coding_outcomes import (
        start_ready_outcomes,
        sync_coding_outcomes,
    )
    person, _, _, _, base = nova_world
    origin = await parent_run(db_session, nova_world)
    issue = (await db_client.post(f"{base}/issues", headers=person.headers,
        json={"type": "task", "title": "Build a change"})).json()
    coding = CodingRun(id=uuid7(), workspace_id=origin.workspace_id, project_id=origin.project_id,
        issue_id=uuid.UUID(issue["id"]), issue_key=issue["key"], session_id=uuid7(), agent=CodingAgent.CODEX,
        status=status, origin_run_id=origin.id, thread_id=origin.thread_id, brief="Implement the requested change",
        repo_full_name="example/project", base_branch="main", commit_sha="a" * 40,
        files_changed=[{"path": "src/main.py", "added": 1, "removed": 0}], diff="+print('changed')",
        summary="Implemented; checks were reported, not independently verified", requested_by_id=origin.requested_by_id,
        created_at=datetime.now(UTC), finished_at=datetime.now(UTC))
    db_session.add(coding)
    await db_session.commit()
    runner = db_client._transport.app.state.runner
    replies = ([tool_call("submit_result", items=[{"severity": "high", "title": "Missing validation", "detail": "Input is unchecked", "refs": ["src/main.py:1"]}]),
                tool_call("submit_specialist_result", summary="One finding", evidence=["src/main.py:1"]), "Review complete."]
               if status is CodingRunStatus.PR_OPENED else [])
    model = agent_script.say(*replies, "Here is the coding outcome and what remains unchecked.")
    await sync_coding_outcomes(runner)
    assert model.received == []
    origin.status = RunStatus.COMPLETED
    await db_session.commit()
    await start_ready_outcomes(runner)
    await sync_coding_outcomes(runner)
    outcomes = list(await db_session.scalars(select(AgentRun).where(AgentRun.source == "coding_outcome")))
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.thread_id == origin.thread_id and outcome.status is RunStatus.COMPLETED
    assert outcome.review_context["revision"] == "a" * 40
    assert "unchecked" in outcome.reply
    children = list(await db_session.scalars(select(AgentRun).where(AgentRun.parent_run_id == outcome.id)))
    if status is CodingRunStatus.PR_OPENED:
        assert len(children) == 1 and children[0].agent == "reviewer"
        assert children[0].review_context["coding_run_id"] == str(coding.id)
    else:
        assert children == []


async def test_automatic_routing_uses_host_task_policy_and_pins_choices(nova_world, db_client, db_session):
    from dotrix_backend.modules.projects.models import Project

    root = await parent_run(db_session, nova_world)
    project = await db_session.get(Project, root.project_id)
    project.specialist_model = "openai:routine"
    project.automatic_model_routing = True
    root.conversation_model = "openai:strong"
    await db_session.commit()
    tasks = SpecialistBatch(tasks=[
        {"key": "design", "agent": "architecture", "brief": "Design auth", "expected_result": "Design"},
        {"key": "review", "agent": "reviewer", "brief": "Check auth", "expected_result": "Review"},
        {"key": "docs", "agent": "documentation", "brief": "Outline docs", "expected_result": "Outline"},
        {"key": "write", "agent": "documentation", "brief": "Write docs", "expected_result": "Docs", "changes_project": True},
    ])
    scheduler = DelegationService(db_client._transport.app.state.runner)
    await scheduler.submit(root.workspace_id, root.id, 1, "policy-batch", tasks)
    children = list(await db_session.scalars(select(AgentRun).where(AgentRun.parent_run_id == root.id)))
    assert {task.task_key: task.model for task in children} == {
        "design": "openai:strong", "review": "openai:strong", "docs": "openai:routine", "write": "openai:strong"}
    project.automatic_model_routing = False
    project.specialist_model = "openai:different"
    await db_session.commit()
    await scheduler.submit(root.workspace_id, root.id, 1, "policy-batch", tasks)
    assert {task.task_key: task.model for task in children}["docs"] == "openai:routine"
