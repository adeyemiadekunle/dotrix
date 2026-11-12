"""Work modes in a project's conversation. Changes wait for approval in every mode, as always;
what the platform enforces by mode is execution intent: only Build engages Kai. Plan saves
versions of the conversation's plan. Build's `start_coding` and Review's coding evidence with
real coding runs are in test_coding.py (they need a connected repo)."""
from httpx import AsyncClient

from dotrix_engine.testing import tool_call


async def _project(db_client: AsyncClient, signup, create_team):
    ada = await signup()
    team = await create_team(ada.headers)
    project = (await db_client.post(f"/v1/workspaces/{team['id']}/projects", json={"key": "KUN", "name": "K"},
                                    headers=ada.headers)).json()
    return ada, f"/v1/workspaces/{team['id']}/projects/{project['id']}"


async def test_discuss_never_engages_kai(db_client: AsyncClient, signup, create_team, agent_script) -> None:
    ada, base = await _project(db_client, signup, create_team)
    model = agent_script.say(
        tool_call("create_issue", type="task", title="Refunds", assignee="coding-agent"),
        "Kai codes only in Build: switch to Build to have it done.",
    )
    run = (await db_client.post(f"{base}/agent/runs", headers=ada.headers, json={
        "message": "How would you build refunds?", "work_mode": "discuss",
    })).json()
    assert run["work_mode"] == "discuss" and "start_coding" not in model.tools_received[0]
    assert "## Mode: Discuss" in model.received[0][0].content
    # A change still waits for approval; handing the issue to Kai is refused, even once approved.
    assert run["status"] == "awaiting_approval", run
    decide = {"decisions": [{"approval_id": run["approvals"][0]["id"], "decision": "approve"}]}
    await db_client.post(f"{base}/agent/runs/{run['id']}/decisions", json=decide, headers=ada.headers)
    said = [m.content for m in model.received[-1] if m.type == "tool"][-1]
    assert "needs Build mode" in said
    assert (await db_client.get(f"{base}/issues", headers=ada.headers)).json() == []


async def test_without_a_mode_the_team_works_as_before(db_client: AsyncClient, signup, create_team, agent_script) -> None:
    ada, base = await _project(db_client, signup, create_team)
    model = agent_script.say(tool_call("write_file", file_path="/dotrix/notes/x.md", content="# X"), "Updated.")
    run = (await db_client.post(f"{base}/agent/runs", headers=ada.headers, json={"message": "Write it down"})).json()
    assert run["status"] == "awaiting_approval" and run["work_mode"] == "discuss"
    offered = set(model.tools_received[0])
    assert "write_file" in offered and not offered & {"start_coding", "save_plan", "coding_evidence"}


async def test_plan_saves_versions_of_the_conversation_s_plan(
    db_client: AsyncClient, signup, create_team, agent_script
) -> None:
    ada, base = await _project(db_client, signup, create_team)
    plan = {
        "title": "Refunds", "summary": "Let support refund a payment within a week.",
        "acceptance_criteria": ["refund() returns the amount", "Refunds after 7 days are refused"],
        "tasks": [{"title": "Add refund()", "detail": "In src/payments.py"},
                  {"title": "Test it", "depends_on": [1]}],
        "open_questions": ["Partial refunds?"],
    }
    model = agent_script.say(tool_call("save_plan", **plan), "Saved the plan: two tasks, one open question.")
    first = (await db_client.post(f"{base}/agent/runs", headers=ada.headers, json={
        "message": "Plan refunds", "work_mode": "plan",
    })).json()
    assert first["status"] == "completed", first
    assert "save_plan" in model.tools_received[0] and "start_coding" not in model.tools_received[0]
    thread = first["thread_id"]

    # A task that depends on one that isn't there is refused; the plan is revised and saved again.
    agent_script.say(
        tool_call("save_plan", call_id="bad", **{**plan, "tasks": [{"title": "x", "depends_on": [3]}]}),
        tool_call("save_plan", call_id="good", **{**plan, "open_questions": []}),
        "Revised: partial refunds are out of scope.",
    )
    await db_client.post(f"{base}/agent/runs", headers=ada.headers, json={
        "message": "No partial refunds", "work_mode": "plan", "thread_id": thread,
    })
    plans = (await db_client.get(f"{base}/agent/threads/{thread}/plans", headers=ada.headers)).json()
    assert [p["version"] for p in plans] == [1, 2]
    assert plans[0]["tasks"][1] == {"title": "Test it", "detail": "", "depends_on": [1]}
    assert plans[0]["open_questions"] == ["Partial refunds?"] and plans[1]["open_questions"] == []
    assert plans[0]["run_id"] == first["id"]


async def test_a_conversation_s_plans_are_as_private_as_the_conversation(
    db_client: AsyncClient, signup, create_team, add_member, agent_script
) -> None:
    from dotrix_backend.modules.workspaces.models import Role

    ada, base = await _project(db_client, signup, create_team)
    bob = await signup(email="bob@example.com", name="Bob")
    await add_member(base.split("/")[3], bob.id, Role.MEMBER)
    agent_script.say(tool_call("save_plan", title="T", summary="S", acceptance_criteria=[], tasks=[{"title": "x"}]), "Saved.")
    run = (await db_client.post(f"{base}/agent/runs", headers=ada.headers, json={
        "message": "Plan it", "work_mode": "plan",
    })).json()
    assert (await db_client.get(f"{base}/agent/threads/{run['thread_id']}/plans", headers=bob.headers)).status_code == 404


async def test_review_reads_the_conversation_s_coding(db_client: AsyncClient, signup, create_team, agent_script) -> None:
    ada, base = await _project(db_client, signup, create_team)
    model = agent_script.say(tool_call("coding_evidence"), "Nothing was coded from this conversation yet.")
    run = (await db_client.post(f"{base}/agent/runs", headers=ada.headers, json={
        "message": "What changed?", "work_mode": "review",
    })).json()
    assert run["status"] == "completed", run
    assert "coding_evidence" in model.tools_received[0] and "start_coding" not in model.tools_received[0]
    said = [m.content for m in model.received[1] if m.type == "tool"]
    assert any("No coding has been started" in str(c) for c in said)


async def test_plan_does_not_offer_project_changes(db_client, signup, create_team, agent_script):
    ada, base = await _project(db_client, signup, create_team)
    model = agent_script.say("I can read and save a plan; switch to Build for changes.")
    run = (await db_client.post(f"{base}/agent/runs", headers=ada.headers, json={
        "message": "Plan this feature", "work_mode": "plan",
    })).json()
    assert run["status"] == "completed", run
    offered = set(model.tools_received[0])
    assert "save_plan" in offered
    assert not offered & {"create_issue", "update_issue", "comment_issue", "link_items", "start_coding"}


async def test_build_plan_reference_must_belong_to_the_conversation(db_client, signup, create_team, agent_script):
    ada, base = await _project(db_client, signup, create_team)
    agent_script.say(tool_call("save_plan", title="Private", summary="Private plan", acceptance_criteria=[],
                               tasks=[{"title": "Private task"}]), "Saved.")
    first = (await db_client.post(f"{base}/agent/runs", headers=ada.headers,
                                 json={"message": "Plan", "work_mode": "plan"})).json()
    [plan] = (await db_client.get(f"{base}/agent/threads/{first['thread_id']}/plans", headers=ada.headers)).json()
    agent_script.say("Another conversation.")
    second = (await db_client.post(f"{base}/agent/runs", headers=ada.headers, json={"message": "Hello"})).json()
    response = await db_client.post(f"{base}/agent/runs", headers=ada.headers, json={
        "message": "Build", "work_mode": "build", "thread_id": second["thread_id"], "plan_id": plan["id"],
    })
    assert response.status_code == 404
    response = await db_client.post(f"{base}/agent/runs", headers=ada.headers, json={
        "message": "Discuss", "work_mode": "discuss", "thread_id": first["thread_id"], "plan_id": plan["id"],
    })
    assert response.status_code == 422


async def test_saved_plan_retains_execution_contract(db_client, signup, create_team, agent_script):
    ada, base = await _project(db_client, signup, create_team)
    execution = {
        "repository": "owner/repo", "base_sha": "a" * 40, "constraints": [], "exclusions": [],
        "tasks": [{"key": "api", "task_number": 1, "owned_paths": ["src/api/"],
                   "instructions": "Add the specified endpoint", "checks": [{"command": "pytest", "expected": "passes"}],
                   "stop_conditions": ["The API contract differs"]}],
    }
    model = agent_script.say(tool_call("save_plan", title="API", summary="Add the API", acceptance_criteria=["API works"],
                                      tasks=[{"title": "Implement API"}], execution=execution), "Saved.")
    run = (await db_client.post(f"{base}/agent/runs", headers=ada.headers,
                               json={"message": "Plan API", "work_mode": "plan"})).json()
    assert run["status"] == "completed", run
    assert "save_plan" in model.tools_received[0]
    [plan] = (await db_client.get(f"{base}/agent/threads/{run['thread_id']}/plans", headers=ada.headers)).json()
    assert plan["execution"] == execution
