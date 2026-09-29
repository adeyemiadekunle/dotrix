"""Agents as data: built-ins that owners change, custom agents, project overrides, and runs
that use them (docs/agents-v2.md §4)."""
import pytest
from httpx import AsyncClient

from pmagent_backend.modules.workspaces.models import Role
from pmagent_engine.testing import tool_call

SECURITY = {
    "name": "Security reviewer",
    "description": "Reviews changes for security risks.",
    "instructions": "Look for leaked secrets and unsafe defaults.",
    "tools": ["knowledge.read", "knowledge.search", "knowledge.write", "board.read", "issues.create"],
    "access": {"reviews/security/*": "write"},
    "issue_types": ["bug"],
}


@pytest.fixture
def world(db_client: AsyncClient, create_team, signup, add_member):
    """Ada owns a team with project KUN; Bob is an admin, Cat a member."""

    async def _make():
        ada = await signup()
        bob = await signup(email="bob@example.com", name="Bob")
        cat = await signup(email="cat@example.com", name="Cat")
        team = await create_team(ada.headers)
        await add_member(team["id"], bob.id, Role.ADMIN)
        await add_member(team["id"], cat.id, Role.MEMBER)
        project = (await db_client.post(f"/v1/workspaces/{team['id']}/projects", json={"key": "KUN", "name": "Kunemi"},
                                        headers=ada.headers)).json()
        ws = f"/v1/workspaces/{team['id']}"
        return ada, bob, cat, ws, f"{ws}/projects/{project['id']}"

    return _make


async def save(client: AsyncClient, url: str, headers, agent: dict, **extra):
    return await client.put(url, json={"agent": agent, **extra}, headers=headers)


async def test_the_builtins_are_listed_until_someone_changes_them(world, db_client: AsyncClient) -> None:
    ada, _, cat, ws, _ = await world()
    agents = (await db_client.get(f"{ws}/agents", headers=cat.headers)).json()
    assert [a["handle"] for a in agents] == [
        "project-manager", "product", "architecture", "research", "reviewer", "documentation"
    ]
    assert all(a["source"] == "built_in" and a["version"] is None for a in agents)
    research = next(a for a in agents if a["handle"] == "research")
    assert "spike" in research["issue_types"] and "web.search" in research["tools"]
    catalog = (await db_client.get(f"{ws}/agents/catalog", headers=cat.headers)).json()
    assert "knowledge.write" in {t["id"] for t in catalog["tools"]} and catalog["low_risk_actions"] == ["issues.comment"]


async def test_customise_a_builtin_then_reset_it(world, db_client: AsyncClient, agent_script) -> None:
    ada, _, _, ws, base = await world()
    product = (await db_client.get(f"{ws}/agents/product", headers=ada.headers)).json()
    fields = {k: product[k] for k in ("name", "description", "instructions", "tools", "access", "issue_types", "can_call")}
    changed = await save(db_client, f"{ws}/agents/product", ada.headers,
                         fields | {"instructions": "Write every story as a job to be done."}, note="JTBD")
    assert changed.status_code == 200, changed.text
    assert changed.json()["source"] == "customised" and changed.json()["version"] == 1

    # A run led by the product agent uses the new instructions.
    model = agent_script.say("Here are the stories.")
    run = (await db_client.post(f"{base}/agent/runs", json={"message": "stories?", "agent": "product"},
                                headers=ada.headers)).json()
    assert run["status"] == "completed"
    assert "Write every story as a job to be done." in str(model.received[0][0].content)

    # Stale edits are refused; saving the same thing again is a no-op.
    stale = await save(db_client, f"{ws}/agents/product", ada.headers, fields, base_version=0)
    assert stale.status_code == 409 and stale.json()["type"].endswith("/agent_changed")
    same = await save(db_client, f"{ws}/agents/product", ada.headers,
                      fields | {"instructions": "Write every story as a job to be done."}, base_version=1)
    assert same.json()["version"] == 1

    assert (await db_client.delete(f"{ws}/agents/product", headers=ada.headers)).status_code == 204
    reset = (await db_client.get(f"{ws}/agents/product", headers=ada.headers)).json()
    assert reset["source"] == "built_in" and reset["instructions"] == product["instructions"]
    history = (await db_client.get(f"{ws}/agents/product/versions", headers=ada.headers)).json()
    assert [(v["version"], v["note"]) for v in history] == [(1, "JTBD")]
    restored = (await db_client.post(f"{ws}/agents/product/versions/1/restore", headers=ada.headers)).json()
    assert restored["version"] == 2 and restored["instructions"].startswith("Write every story")

    actions = [e["action"] for e in (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()]
    assert {"agent.customised", "agent.reset"} <= set(actions)


async def test_a_custom_agent_leads_a_chat_and_writes_only_where_its_contract_allows(
    world, db_client: AsyncClient, agent_script
) -> None:
    ada, _, _, ws, base = await world()
    created = await save(db_client, f"{ws}/agents/security", ada.headers, SECURITY)
    assert created.status_code == 200, created.text and created.json()["source"] == "custom"
    assert "security" in [a["handle"] for a in (await db_client.get(f"{base}/agents", headers=ada.headers)).json()]

    agent_script.say(
        tool_call("write_file", file_path="/pmagent/reviews/security/auth.md", content="# Auth review\n"),
        tool_call("write_file", file_path="/pmagent/requirements/auth.md", content="# Changed\n"),
        "Review saved.",
    )
    paused = (await db_client.post(f"{base}/agent/runs", json={"message": "review auth", "agent": "security"},
                                   headers=ada.headers)).json()
    assert paused["status"] == "awaiting_approval" and paused["agent"] == "security"
    done = paused
    while done["status"] == "awaiting_approval":  # each write pauses; approve them all
        pending = [a for a in done["approvals"] if a["status"] == "pending"]
        decisions = [{"approval_id": a["id"], "decision": "approve"} for a in pending]
        done = (await db_client.post(f"{base}/agent/runs/{done['id']}/decisions", json={"decisions": decisions},
                                     headers=ada.headers)).json()
    assert done["status"] == "completed", done

    history = (await db_client.get(f"{base}/knowledge/files/reviews/security/auth.md/versions",
                                   headers=ada.headers)).json()
    assert history[0]["agent"] == "security"
    # Its contract gives it no access to requirements/, so that write was refused even approved.
    missing = await db_client.get(f"{base}/knowledge/files/requirements/auth.md", headers=ada.headers)
    assert missing.status_code == 404

    unknown = await db_client.post(f"{base}/agent/runs", json={"message": "hi", "agent": "marketing"},
                                   headers=ada.headers)
    assert unknown.status_code == 422 and unknown.json()["type"].endswith("/unknown_agent")


async def test_who_may_change_agents(world, db_client: AsyncClient) -> None:
    ada, bob, cat, ws, _ = await world()
    assert (await save(db_client, f"{ws}/agents/security", cat.headers, SECURITY)).status_code == 403
    assert (await save(db_client, f"{ws}/agents/security", bob.headers, SECURITY)).status_code == 200
    # Only owners let an agent act without asking, and only for low-risk actions.
    allow = SECURITY | {"tools": [*SECURITY["tools"], "issues.comment"], "autonomy": {"issues.comment": "allow"}}
    by_admin = await save(db_client, f"{ws}/agents/security", bob.headers, allow, base_version=1)
    assert by_admin.status_code == 403
    by_owner = await save(db_client, f"{ws}/agents/security", ada.headers, allow, base_version=1)
    assert by_owner.status_code == 200 and by_owner.json()["autonomy"] == {"issues.comment": "allow"}
    risky = await save(db_client, f"{ws}/agents/security", ada.headers,
                       allow | {"autonomy": {"issues.create": "allow"}}, base_version=2)
    assert risky.status_code == 422 and "low-risk" in risky.json()["detail"]


@pytest.mark.parametrize(
    ("handle", "agent", "message"),
    [
        ("auto", SECURITY, "reserved"),
        ("coding", SECURITY, "reserved"),
        ("security", SECURITY | {"access": {"agent-rules/*": "write"}}, "agent-rules"),
        ("security", SECURITY | {"tools": ["shell"]}, "Unknown tools"),
        ("security", SECURITY | {"tools": ["knowledge.read"]}, "issues.create"),
    ],
)
async def test_contracts_are_checked(world, db_client: AsyncClient, handle: str, agent: dict, message: str) -> None:
    ada, _, _, ws, _ = await world()
    res = await save(db_client, f"{ws}/agents/{handle}", ada.headers, agent)
    assert res.status_code == 422 and message in res.json()["detail"], res.text


async def test_a_project_overrides_an_agent_for_itself_only(world, db_client: AsyncClient, agent_script) -> None:
    ada, _, _, ws, base = await world()
    research = (await db_client.get(f"{ws}/agents/research", headers=ada.headers)).json()
    fields = {k: research[k] for k in ("name", "description", "instructions", "tools", "access", "issue_types", "can_call")}
    override = await save(db_client, f"{base}/agents/research", ada.headers,
                          fields | {"instructions": "Only cite EU sources."})
    assert override.status_code == 200 and override.json()["scope"] == "project"
    assert (await db_client.get(f"{ws}/agents/research", headers=ada.headers)).json()["source"] == "built_in"

    model = agent_script.say("EU sources say yes.")
    await db_client.post(f"{base}/agent/runs", json={"message": "rules?", "agent": "research"}, headers=ada.headers)
    assert "Only cite EU sources." in str(model.received[0][0].content)

    assert (await db_client.delete(f"{base}/agents/research", headers=ada.headers)).status_code == 204
    assert (await db_client.get(f"{base}/agents/research", headers=ada.headers)).json()["source"] == "built_in"


async def test_an_allowed_comment_needs_no_approval_and_a_blocked_action_is_gone(
    world, db_client: AsyncClient, agent_script
) -> None:
    ada, _, _, ws, base = await world()
    issue = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Rotate keys"}, headers=ada.headers)).json()
    triage = {
        "name": "Triage", "instructions": "Comment on issues; never open them.",
        "tools": ["board.read", "issues.create", "issues.comment"], "issue_types": ["bug"],
        "autonomy": {"issues.comment": "allow", "issues.create": "block"},
    }
    assert (await save(db_client, f"{ws}/agents/triage", ada.headers, triage)).status_code == 200

    agent_script.say(
        tool_call("comment_issue", key=issue["key"], text="Looks like a duplicate of nothing."),
        tool_call("create_issue", type="bug", title="Should not exist"),
        "Commented.",
    )
    done = (await db_client.post(f"{base}/agent/runs", json={"message": "triage it", "agent": "triage"},
                                 headers=ada.headers)).json()
    assert done["status"] == "completed", done  # nothing paused for approval
    log = (await db_client.get(f"{base}/issues/{issue['key']}", headers=ada.headers)).json()["log"]
    comment = next(e for e in log if e["kind"] == "commented")
    assert comment["author_agent"] == "triage" and "duplicate" in comment["body"]
    titles = [i["title"] for i in (await db_client.get(f"{base}/issues", headers=ada.headers)).json()]
    assert "Should not exist" not in titles  # blocked: it had no create tool
    audit = (await db_client.get(f"{ws}/audit", headers=ada.headers)).json()
    allowed = next(e for e in audit if e["action"] == "issues.comment.allowed")
    assert allowed["agent"] == "triage" and allowed["details"]["rule"] == {"agent": "triage", "action": "issues.comment", "version": 1}
