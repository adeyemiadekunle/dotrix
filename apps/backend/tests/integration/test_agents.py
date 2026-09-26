"""Agent runs through the API, with a scripted model (no API key needed)."""
import pytest
from httpx import AsyncClient

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
