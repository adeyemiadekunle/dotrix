"""Conversations across projects: read-only, over several projects (or none), private to
whoever started them, and only while they still see every project in them."""
from httpx import AsyncClient

from pmagent_backend.modules.workspaces.models import Role
from pmagent_engine.testing import tool_call


async def _world(db_client: AsyncClient, signup, create_team, add_member):
    ada = await signup()
    cat = await signup(email="cat@example.com", name="Cat")
    team = await create_team(ada.headers)
    await add_member(team["id"], cat.id, Role.MEMBER)
    ws = f"/v1/workspaces/{team['id']}"
    projects = {}
    for key, name in (("KUN", "Kunemi"), ("OPS", "Operations")):
        projects[key] = (await db_client.post(f"{ws}/projects", json={"key": key, "name": name}, headers=ada.headers)).json()
    kun = f"{ws}/projects/{projects['KUN']['id']}"
    ops = f"{ws}/projects/{projects['OPS']['id']}"
    await db_client.put(f"{kun}/knowledge/files/requirements/refunds.md", headers=ada.headers,
                        json={"content": "# Refunds\n\nCustomers get refunds within a week.\n"})
    await db_client.post(f"{ops}/issues", json={"type": "task", "title": "Rota for the warehouse"}, headers=ada.headers)
    return ada, cat, ws, projects, kun, ops


def _results(model, name: str) -> list[str]:
    return [m.content for m in model.received[-1] if getattr(m, "name", None) == name]


async def test_a_conversation_reads_several_projects_and_changes_nothing(
    db_client: AsyncClient, signup, create_team, add_member, agent_script
) -> None:
    ada, cat, ws, projects, kun, ops = await _world(db_client, signup, create_team, add_member)
    model = agent_script.say(
        tool_call("search_knowledge", query="refunds"),
        tool_call("list_issues", project="OPS"),
        tool_call("read_file", file_path="/pmagent/KUN/requirements/refunds.md"),
        tool_call("write_file", file_path="/pmagent/KUN/requirements/refunds.md", content="# Gone\n"),
        "KUN refunds take a week; OPS is planning the warehouse rota.",
    )
    res = await db_client.post(f"{ws}/conversations/runs", headers=ada.headers, json={
        "message": "Summarise refunds and what Operations is doing",
        "project_ids": [projects["KUN"]["id"], projects["OPS"]["id"]],
    })
    assert res.status_code == 202, res.text
    run = (await db_client.get(f"{ws}/conversations/runs/{res.json()['id']}", headers=ada.headers)).json()
    assert run["status"] == "completed", run
    assert run["reply"].startswith("KUN refunds take a week") and run["approvals"] == []
    assert sorted(run["project_ids"]) == sorted([projects["KUN"]["id"], projects["OPS"]["id"]])

    system = model.received[0][0].content
    assert "## KUN: Kunemi" in system and "## OPS: Operations" in system and "A conversation across projects" in system
    assert "/pmagent/KUN/requirements/refunds.md" in _results(model, "search_knowledge")[0]
    assert "Rota for the warehouse" in str(_results(model, "list_issues")[0])
    assert "within a week" in _results(model, "read_file")[0]
    assert _results(model, "write_file") and "within a week" in (
        await db_client.get(f"{kun}/knowledge/files/requirements/refunds.md", headers=ada.headers)
    ).json()["content"]  # refused: nothing changed

    # It isn't any project's run, and it's Ada's alone.
    assert all(r["id"] != run["id"] for r in (await db_client.get(f"{kun}/agent/runs", headers=ada.headers)).json())
    assert (await db_client.get(f"{ws}/conversations/runs/{run['id']}", headers=cat.headers)).status_code == 404
    [conversation] = (await db_client.get(f"{ws}/conversations", headers=ada.headers)).json()
    assert conversation["project_keys"] == ["KUN", "OPS"] and conversation["thread_id"] == run["thread_id"]
    assert (await db_client.get(f"{ws}/conversations", headers=cat.headers)).json() == []

    # Continuing keeps its projects; others are refused.
    agent_script.say("Still those two.")
    again = await db_client.post(f"{ws}/conversations/runs", headers=ada.headers,
                                 json={"message": "And now?", "thread_id": run["thread_id"]})
    assert again.status_code == 202 and again.json()["project_ids"] == run["project_ids"]
    other = await db_client.post(f"{ws}/conversations/runs", headers=ada.headers, json={
        "message": "Only KUN", "thread_id": run["thread_id"], "project_ids": [projects["KUN"]["id"]],
    })
    assert other.status_code == 409
    runs = (await db_client.get(f"{ws}/conversations/runs", params={"thread_id": run["thread_id"]},
                                headers=ada.headers)).json()
    assert [r["message"] for r in runs] == ["And now?", "Summarise refunds and what Operations is doing"]


async def test_about_no_project_and_only_projects_you_see(
    db_client: AsyncClient, signup, create_team, add_member, agent_script
) -> None:
    ada, cat, ws, projects, kun, _ = await _world(db_client, signup, create_team, add_member)
    model = agent_script.say("Ask in KUN or OPS.", "Refunds are KUN's.")
    general = await db_client.post(f"{ws}/conversations/runs", json={"message": "Where do I ask about refunds?"},
                                   headers=cat.headers)
    assert general.status_code == 202, general.text
    assert "- KUN: Kunemi" in model.received[0][0].content and "- OPS: Operations" in model.received[0][0].content

    # Cat starts one about KUN; when KUN is restricted away from Cat, it's gone for Cat.
    about = await db_client.post(f"{ws}/conversations/runs", headers=cat.headers,
                                 json={"message": "Refunds?", "project_ids": [projects["KUN"]["id"]]})
    assert about.status_code == 202
    await db_client.patch(kun, json={"access": "restricted"}, headers=ada.headers)
    assert [c["project_keys"] for c in (await db_client.get(f"{ws}/conversations", headers=cat.headers)).json()] == [[]]
    assert (await db_client.get(f"{ws}/conversations/runs/{about.json()['id']}", headers=cat.headers)).status_code == 404
    refused = await db_client.post(f"{ws}/conversations/runs", headers=cat.headers,
                                   json={"message": "x", "project_ids": [projects["KUN"]["id"]]})
    assert refused.status_code == 404
