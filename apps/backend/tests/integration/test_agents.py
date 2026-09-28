"""Agent runs through the API, with a scripted model (no API key needed)."""
import pytest
from httpx import AsyncClient
from langchain_core.messages import AIMessage

from pmagent_backend.modules.workspaces.models import Role
from pmagent_engine.testing import tool_call


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


async def run(client: AsyncClient, base: str, headers, message: str = "hello", **extra):
    res = await client.post(f"{base}/agent/runs", json={"message": message, **extra}, headers=headers)
    assert res.status_code == 202, res.text
    return res.json()


async def decide(client: AsyncClient, base: str, run_: dict, headers, *choices):
    """choices: ("approve",) or ("reject", "reason") per pending approval, in order."""
    pending = [a for a in run_["approvals"] if a["status"] == "pending"]
    decisions = [
        {"approval_id": a["id"], "decision": c[0], "reason": c[1] if len(c) > 1 else None}
        for a, c in zip(pending, choices, strict=True)
    ]
    return await client.post(
        f"{base}/agent/runs/{run_['id']}/decisions", json={"decisions": decisions}, headers=headers
    )


async def read(client: AsyncClient, base: str, path: str, headers) -> str:
    return (await client.get(f"{base}/knowledge/files/{path}", headers=headers)).json()["content"]


# -- chat -----------------------------------------------------------------------------


async def test_chat_run_completes(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    model = agent_script.say("We're in the discovery phase.")
    done = await run(db_client, base, ada.headers, "Where are we?")
    assert done["status"] == "completed" and done["kind"] == "chat"
    assert done["reply"] == "We're in the discovery phase."
    assert done["requested_by_id"] == ada.id and done["approvals"] == []
    # The project's agent rules reach the model.
    system = str(model.received[0][0].content)
    assert "You are working on the Kunemi project." in system

    again = (await db_client.get(f"{base}/agent/runs/{done['id']}", headers=ada.headers)).json()
    assert again["reply"] == done["reply"]


async def test_conversation_threads(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    agent_script.say("First answer.", "Second answer.")
    first = await run(db_client, base, ada.headers, "one")
    second = await run(db_client, base, ada.headers, "two", thread_id=first["thread_id"])
    assert second["thread_id"] == first["thread_id"] and second["reply"] == "Second answer."
    thread = (
        await db_client.get(f"{base}/agent/runs", params={"thread_id": first["thread_id"]}, headers=ada.headers)
    ).json()
    assert [r["message"] for r in thread] == ["two", "one"]


async def test_new_threads_get_titles(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    model = agent_script.say("Here's the board.", "And more.")
    first = await run(db_client, base, ada.headers, "Hi, can you tell me what's open on the board right now, and what's blocked?")
    # Made from the message by rules (titles.py): no model call for it.
    assert first["title"] == "What's open on the board right now…"
    assert len(model.received) == 1
    follow_up = await run(db_client, base, ada.headers, "Thanks", thread_id=first["thread_id"])
    assert follow_up["title"] is None  # only a thread's first run carries its title
    assert len(model.received) == 2


async def test_built_in_requests_have_fixed_titles(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    agent_script.say("All quiet.")
    brief = (await db_client.post(f"{base}/agent/briefing", headers=ada.headers)).json()
    assert brief["title"] == "Daily briefing"


def empty_turn() -> AIMessage:
    """How Gemini sometimes ends a turn after tool calls: no text, no tool calls."""
    return AIMessage(content=[], response_metadata={"finish_reason": "STOP"})


async def test_an_empty_final_turn_is_asked_again(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    model = agent_script.say(
        tool_call("read_file", file_path="/pmagent/project.md"),
        empty_turn(),
        "Kunemi is a logistics platform.",
    )
    done = await run(db_client, base, ada.headers, "What is this project about?")
    assert done["status"] == "completed" and done["reply"] == "Kunemi is a logistics platform."
    # The follow-up replaces the empty turn, which some providers refuse to see in the history.
    follow_up = model.received[-1]
    assert follow_up[-1].type == "human" and "ended without a reply" in str(follow_up[-1].content)
    assert follow_up[-2].type == "tool"
    # The conversation shows the person's message, not the follow-up.
    [shown] = (await db_client.get(f"{base}/agent/runs", headers=ada.headers)).json()
    assert shown["message"] == "What is this project about?"


async def test_thinking_alone_is_not_a_reply(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    agent_script.say(
        AIMessage(content=[{"type": "thinking", "thinking": "Let me summarise."}]), "Here's the summary."
    )
    done = await run(db_client, base, ada.headers, "Summarise")
    assert done["reply"] == "Here's the summary."


async def test_text_before_an_empty_final_turn_is_the_reply(
    project, db_client: AsyncClient, agent_script
) -> None:
    ada, _, base = await project()
    answered = tool_call("read_file", file_path="/pmagent/project.md")
    answered.content = "It's a logistics platform. Checking the details."
    model = agent_script.say(answered, empty_turn(), "unused")
    done = await run(db_client, base, ada.headers, "What is this?")
    assert done["reply"] == "It's a logistics platform. Checking the details."
    assert len(model.received) == 2  # not asked again


async def test_no_reply_even_when_asked_again_fails(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    agent_script.say(empty_turn(), AIMessage(content=""))
    done = await run(db_client, base, ada.headers, "Hello?")
    assert done["status"] == "failed" and not done["reply"]
    assert "finished without writing a reply" in done["error"]


# -- approvals --------------------------------------------------------------------------


async def test_write_waits_for_approval_then_applies(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    agent_script.say(
        tool_call("write_file", file_path="/pmagent/roadmap.md", content="# Roadmap\n\nPhase 1: core.\n"),
        "Action complete: updated roadmap.md.",
    )
    paused = await run(db_client, base, ada.headers, "Update the roadmap with phase 1")
    assert paused["status"] == "awaiting_approval"
    [approval] = paused["approvals"]
    assert approval["tool"] == "write_file" and approval["target"] == "/pmagent/roadmap.md"
    assert "+Phase 1: core." in approval["diff"] and "-_Phases, milestones" in approval["diff"]
    # Nothing is written before approval.
    assert "Phase 1" not in await read(db_client, base, "roadmap.md", ada.headers)
    queue = (await db_client.get(f"{base}/agent/approvals", headers=ada.headers)).json()
    assert [a["id"] for a in queue] == [approval["id"]]

    res = await decide(db_client, base, paused, ada.headers, ("approve",))
    assert res.status_code == 200, res.text
    done = res.json()
    assert done["status"] == "completed" and done["reply"] == "Action complete: updated roadmap.md."
    assert done["approvals"][0]["status"] == "approved" and done["approvals"][0]["decided_by_id"] == ada.id
    assert "Phase 1: core." in await read(db_client, base, "roadmap.md", ada.headers)

    [latest, *_] = (await db_client.get(f"{base}/knowledge/files/roadmap.md/versions", headers=ada.headers)).json()
    assert (latest["author_type"], latest["agent"]) == ("agent", "project-manager")
    assert latest["instructed_by_id"] == ada.id and latest["approved_by_id"] == ada.id
    assert (await db_client.get(f"{base}/agent/approvals", headers=ada.headers)).json() == []


async def test_workspace_approvals_queue(
    project, db_client: AsyncClient, agent_script, add_member, signup, create_team
) -> None:
    ada, team, base = await project()
    agent_script.say(
        tool_call("write_file", file_path="/pmagent/roadmap.md", content="# Roadmap\n\nPhase 1.\n"),
        "Done.",
    )
    paused = await run(db_client, base, ada.headers, "Update the roadmap")
    queue_url = f"/v1/workspaces/{team['id']}/approvals"

    [item] = (await db_client.get(queue_url, headers=ada.headers)).json()
    assert item["id"] == paused["approvals"][0]["id"] and item["run_id"] == paused["id"]
    assert (item["project_key"], item["project_name"]) == ("KUN", "Kunemi")
    assert item["run_message"] == "Update the roadmap" and item["requested_by_id"] == ada.id
    assert "+Phase 1." in item["diff"]

    guest = await signup(email="guest@example.com", name="Guest")
    await add_member(team["id"], guest.id, Role.GUEST)
    assert (await db_client.get(queue_url, headers=guest.headers)).status_code == 403
    eve = await signup(email="eve@example.com", name="Eve")
    await create_team(eve.headers)
    assert (await db_client.get(queue_url, headers=eve.headers)).status_code == 404  # not her workspace

    assert (await decide(db_client, base, paused, ada.headers, ("approve",))).status_code == 200
    assert (await db_client.get(queue_url, headers=ada.headers)).json() == []


async def test_rejected_write_is_not_applied(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    model = agent_script.say(
        tool_call("write_file", file_path="/pmagent/vision.md", content="Something else"),
        "Understood, I left the vision as it is.",
    )
    paused = await run(db_client, base, ada.headers, "rewrite the vision")
    before = await read(db_client, base, "vision.md", ada.headers)
    done = (await decide(db_client, base, paused, ada.headers, ("reject", "Keep the current vision"))).json()
    assert done["status"] == "completed" and done["approvals"][0]["reason"] == "Keep the current vision"
    assert await read(db_client, base, "vision.md", ada.headers) == before
    # The reason goes back to the agent.
    assert "Keep the current vision" in str(model.received[-1])


async def test_folder_permissions_apply_even_after_approval(
    project, db_client: AsyncClient, agent_script
) -> None:
    ada, _, base = await project()
    model = agent_script.say(
        # The Project Manager may only read requirements/ (Product owns it).
        tool_call("write_file", file_path="/pmagent/requirements/product.md", content="PM edit"),
        "I'll ask the Product agent instead.",
    )
    paused = await run(db_client, base, ada.headers, "change the requirements")
    done = (await decide(db_client, base, paused, ada.headers, ("approve",))).json()
    assert done["status"] == "completed"
    assert await read(db_client, base, "requirements/product.md", ada.headers) == "# Product requirements\n"
    assert "can't write requirements/product.md" in str(model.received[-1])


async def test_subagent_writes_are_attributed_to_its_role(
    project, db_client: AsyncClient, agent_script
) -> None:
    ada, _, base = await project()
    agent_script.say(
        # PM delegates to the Product agent...
        tool_call("task", description="Add a scheduled-delivery story", subagent_type="product-agent"),
        # ...which writes its own folder...
        tool_call("write_file", file_path="/pmagent/requirements/product.md", content="# Scheduled delivery"),
        "Story written.",
        # ...and the PM reports back.
        "Product added the story.",
    )
    paused = await run(db_client, base, ada.headers, "add a scheduled delivery story")
    assert paused["status"] == "awaiting_approval"
    done = (await decide(db_client, base, paused, ada.headers, ("approve",))).json()
    assert done["status"] == "completed", done
    assert await read(db_client, base, "requirements/product.md", ada.headers) == "# Scheduled delivery"
    [latest, *_] = (
        await db_client.get(f"{base}/knowledge/files/requirements/product.md/versions", headers=ada.headers)
    ).json()
    assert latest["agent"] == "product"


async def test_briefing_is_read_only(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    agent_script.say(
        tool_call("write_file", file_path="/pmagent/progress/blocked.md", content="changed"),
        "Briefing: discovery phase, nothing blocked.",
    )
    res = await db_client.post(f"{base}/agent/briefing", headers=ada.headers)
    assert res.status_code == 202
    brief = res.json()
    assert brief["kind"] == "briefing" and brief["status"] == "completed"
    assert brief["reply"] == "Briefing: discovery phase, nothing blocked."
    assert brief["approvals"] == []
    assert await read(db_client, base, "progress/blocked.md", ada.headers) == "# Blocked\n"


# -- rules and errors -----------------------------------------------------------------------


async def test_decisions_must_cover_every_pending_approval(
    project, db_client: AsyncClient, agent_script
) -> None:
    ada, _, base = await project()
    agent_script.say(tool_call("write_file", file_path="/pmagent/vision.md", content="x"), "ok")
    paused = await run(db_client, base, ada.headers)
    url = f"{base}/agent/runs/{paused['id']}/decisions"
    bogus = {"decisions": [{"approval_id": "00000000-0000-0000-0000-000000000000", "decision": "approve"}]}
    assert (await db_client.post(url, json=bogus, headers=ada.headers)).status_code == 422
    assert (await decide(db_client, base, paused, ada.headers, ("approve",))).status_code == 200
    # Already decided: the run isn't waiting any more.
    assert (await decide(db_client, base, paused, ada.headers, ("approve",))).status_code == 409


async def test_thread_rules(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    agent_script.say(tool_call("write_file", file_path="/pmagent/vision.md", content="x"), "ok")
    paused = await run(db_client, base, ada.headers)
    busy = await db_client.post(
        f"{base}/agent/runs", json={"message": "and?", "thread_id": paused["thread_id"]}, headers=ada.headers
    )
    assert busy.status_code == 409 and busy.json()["type"].endswith("/thread_busy")
    unknown = await db_client.post(
        f"{base}/agent/runs",
        json={"message": "hi", "thread_id": "00000000-0000-0000-0000-000000000000"},
        headers=ada.headers,
    )
    assert unknown.status_code == 404


async def test_no_model_key_is_503(project, db_client: AsyncClient) -> None:
    ada, _, base = await project()
    res = await db_client.post(f"{base}/agent/runs", json={"message": "hi"}, headers=ada.headers)
    assert res.status_code == 503 and res.json()["type"].endswith("/model_unavailable")


async def test_agent_permissions(project, db_client: AsyncClient, agent_script, add_member, signup) -> None:
    ada, team, base = await project()
    guest = await signup(email="guest@example.com", name="Guest")
    eve = await signup(email="eve@example.com", name="Eve")
    await add_member(team["id"], guest.id, Role.GUEST)
    agent_script.say(tool_call("write_file", file_path="/pmagent/vision.md", content="x"), "ok")
    paused = await run(db_client, base, ada.headers)

    body = {"message": "hi"}
    # Guests are workspace members without chat permission; outsiders can't see the project.
    assert (await db_client.post(f"{base}/agent/runs", json=body, headers=guest.headers)).status_code == 403
    assert (await db_client.post(f"{base}/agent/runs", json=body, headers=eve.headers)).status_code == 404
    assert (await decide(db_client, base, paused, eve.headers, ("approve",))).status_code == 404


async def test_audit_log(project, db_client: AsyncClient, agent_script, add_member, signup) -> None:
    ada, team, base = await project()
    bob = await signup(email="bob@example.com", name="Bob")
    await add_member(team["id"], bob.id, Role.MEMBER)
    # roadmap.md belongs to the Project Manager, so the approved write goes through.
    agent_script.say(tool_call("write_file", file_path="/pmagent/roadmap.md", content="New"), "done")
    paused = await run(db_client, base, ada.headers)
    await decide(db_client, base, paused, ada.headers, ("approve",))

    audit_url = f"/v1/workspaces/{team['id']}/audit"
    events = (await db_client.get(audit_url, headers=ada.headers)).json()
    actions = [e["action"] for e in events]
    for expected in ("agent_run.started", "agent_run.awaiting_approval", "approval.approved",
                     "knowledge.write", "agent_run.completed"):
        assert expected in actions, expected
    write = next(e for e in events if e["action"] == "knowledge.write" and e["agent"])
    assert write["target"] == "roadmap.md" and write["agent"] == "project-manager"
    assert write["instructed_by_id"] == ada.id and write["approved_by_id"] == ada.id
    # Only owners and admins read the audit log.
    assert (await db_client.get(audit_url, headers=bob.headers)).status_code == 403



# -- project setup: the architecture overview ---------------------------------------------


async def test_architecture_draft_is_setup_work(
    project, db_client: AsyncClient, agent_script, add_member, signup
) -> None:
    ada, team, base = await project()
    bob = await signup(email="bob@example.com", name="Bob")
    await add_member(team["id"], bob.id, Role.MEMBER)
    url = f"{base}/agent/architecture-draft"
    body = {"repo_summary": "apps/web (Next.js), apps/api (FastAPI), Postgres"}

    assert (await db_client.post(url, json=body, headers=bob.headers)).status_code == 403
    model = agent_script.say(
        tool_call("write_file", file_path="/pmagent/architecture/overview.md", content="# Overview\nNext.js + FastAPI"),
        "Drafted the overview.",
    )
    paused = (await db_client.post(url, json=body, headers=ada.headers)).json()
    assert paused["status"] == "awaiting_approval"
    assert paused["approvals"][0]["target"] == "/pmagent/architecture/overview.md"
    first_prompt = str(model.received[0])
    assert "draft the architecture overview" in first_prompt and "apps/api (FastAPI)" in first_prompt
    events = (await db_client.get(f"/v1/workspaces/{team['id']}/audit", params={"action": "project.architecture_draft"},
                                  headers=ada.headers)).json()
    assert events and events[0]["details"] == {"with_repo_summary": True}


async def test_only_owners_and_admins_approve_architecture_changes(
    project, db_client: AsyncClient, agent_script, add_member, signup
) -> None:
    ada, team, base = await project()
    bob = await signup(email="bob@example.com", name="Bob")
    await add_member(team["id"], bob.id, Role.MEMBER)
    agent_script.say(
        tool_call("write_file", file_path="/pmagent/architecture/overview.md", content="# Rewritten by a chat"),
        "Done.",
    )
    # A member chats and the agent proposes an architecture change...
    paused = await run(db_client, base, bob.headers, "rewrite the architecture overview")
    # ...which the member can't approve; the run keeps waiting.
    denied = await decide(db_client, base, paused, bob.headers, ("approve",))
    assert denied.status_code == 403
    # Even where the workspace lets members approve agent changes, architecture stays with
    # owners and admins.
    grant = await db_client.patch(f"/v1/workspaces/{team['id']}", json={"member_permissions": ["agents:approve"]}, headers=ada.headers)
    assert grant.status_code == 200
    denied = await decide(db_client, base, paused, bob.headers, ("approve",))
    assert denied.status_code == 403 and "owner or admin" in denied.json()["detail"]
    still = (await db_client.get(f"{base}/agent/runs/{paused['id']}", headers=ada.headers)).json()
    assert still["status"] == "awaiting_approval"
    # An owner decides it.
    assert (await decide(db_client, base, paused, ada.headers, ("reject", "Keep ours"))).status_code == 200


# -- token usage ------------------------------------------------------------------------------


def used(message: AIMessage | str, input_tokens: int, output_tokens: int) -> AIMessage:
    """A scripted reply that reports its token usage, as providers do."""
    reply = message if isinstance(message, AIMessage) else AIMessage(content=message)
    reply.usage_metadata = {
        "input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens,
    }
    return reply


async def test_a_run_records_its_model_and_tokens(project, db_client: AsyncClient, agent_script) -> None:
    ada, team, base = await project()
    agent_script.say(
        used(tool_call("read_file", file_path="/pmagent/project.md"), 100, 10),
        used("It's a logistics platform.", 150, 20),
    )
    done = await run(db_client, base, ada.headers, "What is this?")
    assert done["status"] == "completed"
    assert (done["input_tokens"], done["output_tokens"]) == (250, 30)
    project_ = (await db_client.get(base, headers=ada.headers)).json()
    assert done["model"] == project_["model"]

    events = (await db_client.get(f"/v1/workspaces/{team['id']}/audit", headers=ada.headers)).json()
    completed = next(e for e in events if e["action"] == "agent_run.completed")
    assert completed["details"] == {"input_tokens": 250, "output_tokens": 30}


async def test_tokens_add_up_across_an_approval(project, db_client: AsyncClient, agent_script) -> None:
    ada, team, base = await project()
    agent_script.say(
        used(tool_call("write_file", file_path="/pmagent/roadmap.md", content="New"), 100, 10),
        used("Updated the roadmap.", 120, 5),
    )
    paused = await run(db_client, base, ada.headers, "Update the roadmap")
    assert paused["status"] == "awaiting_approval"
    assert (paused["input_tokens"], paused["output_tokens"]) == (100, 10)
    done = (await decide(db_client, base, paused, ada.headers, ("approve",))).json()
    assert done["status"] == "completed"
    assert (done["input_tokens"], done["output_tokens"]) == (220, 15)

    events = (await db_client.get(f"/v1/workspaces/{team['id']}/audit", headers=ada.headers)).json()
    waiting = next(e for e in events if e["action"] == "agent_run.awaiting_approval")
    assert waiting["details"] == {"pending_actions": 1, "input_tokens": 100, "output_tokens": 10}
    completed = next(e for e in events if e["action"] == "agent_run.completed")
    assert completed["details"] == {"input_tokens": 120, "output_tokens": 5}  # this step's tokens


async def test_subagent_calls_are_counted(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    agent_script.say(
        used(tool_call("task", description="Summarise the vision", subagent_type="research-agent"), 100, 10),
        used("The vision is a logistics platform.", 40, 8),  # the subagent
        used("Research says: logistics.", 130, 6),  # the PM again
    )
    done = await run(db_client, base, ada.headers, "Ask research about the vision")
    assert done["status"] == "completed", done
    assert (done["input_tokens"], done["output_tokens"]) == (270, 24)


async def test_a_failed_run_keeps_its_tokens(project, db_client: AsyncClient, agent_script) -> None:
    ada, team, base = await project()
    agent_script.say(used(empty_turn(), 80, 0), used(AIMessage(content=""), 90, 0))
    done = await run(db_client, base, ada.headers, "Hello?")
    assert done["status"] == "failed"
    assert (done["input_tokens"], done["output_tokens"]) == (170, 0)
    events = (await db_client.get(f"/v1/workspaces/{team['id']}/audit", headers=ada.headers)).json()
    failed = next(e for e in events if e["action"] == "agent_run.failed")
    assert failed["details"]["input_tokens"] == 170 and failed["details"]["output_tokens"] == 0


async def test_only_owners_and_admins_see_token_usage(
    project, db_client: AsyncClient, agent_script, signup, add_member
) -> None:
    ada, team, base = await project()
    bob = await signup(email="bob@example.com", name="Bob")
    await add_member(team["id"], bob.id, Role.MEMBER)
    agent_script.say(used("It's a logistics platform.", 150, 20), used("Still logistics.", 160, 4))
    done = await run(db_client, base, bob.headers, "What is this?")  # Bob started it himself
    assert done["status"] == "completed"
    assert (done["model"], done["input_tokens"], done["output_tokens"]) == (None, None, None)
    listed = (await db_client.get(f"{base}/agent/runs", headers=bob.headers)).json()
    assert all(r["input_tokens"] is None and r["model"] is None for r in listed)

    as_owner = (await db_client.get(f"{base}/agent/runs/{done['id']}", headers=ada.headers)).json()
    assert (as_owner["input_tokens"], as_owner["output_tokens"]) == (150, 20) and as_owner["model"]
    await add_member(team["id"], (await signup(email="cy@example.com", name="Cy")).id, Role.ADMIN)
    cy = await db_client.post("/v1/auth/login", json={"email": "cy@example.com", "password": "correct horse battery"})
    as_admin = (
        await db_client.get(f"{base}/agent/runs/{done['id']}", headers={"Authorization": f"Bearer {cy.json()['access_token']}"})
    ).json()
    assert as_admin["input_tokens"] == 150


async def test_past_briefings_are_listed_by_kind(project, db_client: AsyncClient, agent_script) -> None:
    ada, _, base = await project()
    agent_script.say("Chat answer.", "Briefing one.", "Briefing two.")
    await run(db_client, base, ada.headers, "What's open?")
    first = (await db_client.post(f"{base}/agent/briefing", headers=ada.headers)).json()
    second = (await db_client.post(f"{base}/agent/briefing", headers=ada.headers)).json()
    briefings = (await db_client.get(f"{base}/agent/runs", params={"kind": "briefing"}, headers=ada.headers)).json()
    assert [b["id"] for b in briefings] == [second["id"], first["id"]]  # newest first, chats left out
    assert [b["reply"] for b in briefings] == ["Briefing two.", "Briefing one."]
    bad = await db_client.get(f"{base}/agent/runs", params={"kind": "nonsense"}, headers=ada.headers)
    assert bad.status_code == 422
