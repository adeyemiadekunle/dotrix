"""run_script on a real run: Nova reads several things in one sandboxed step (agents/scripts.py), on DeepAgents.

The fx side runs in test_fx_changes.py, where the real libfx host is set up."""
import pytest
from httpx import AsyncClient

from dotrix_engine.testing import tool_call

DOC = "requirements/zones.md"


@pytest.fixture
def project(db_client: AsyncClient, create_team, signup):
    async def _make():
        ada = await signup()
        team = await create_team(ada.headers)
        created = (await db_client.post(f"/v1/workspaces/{team['id']}/projects", json={"key": "KUN", "name": "Kunemi"},
                                        headers=ada.headers)).json()
        base = f"/v1/workspaces/{team['id']}/projects/{created['id']}"
        wrote = await db_client.put(f"{base}/knowledge/files/{DOC}", headers=ada.headers,
                                    json={"content": "# Zones\n\nA refund goes back to the zone it was paid in.\n", "base_version": 0})
        assert wrote.status_code == 200, wrote.text
        for title in ("Refund flow", "Zone picker", "Invoice footer"):
            made = await db_client.post(f"{base}/issues", json={"title": title}, headers=ada.headers)
            assert made.status_code == 201, made.text
        return ada, base
    return _make


async def _ask(client: AsyncClient, base: str, headers, message: str) -> dict:
    done = await client.post(f"{base}/agent/runs", json={"message": message}, headers=headers)
    assert done.status_code in (200, 201, 202), done.text
    return done.json()


async def test_nova_reads_a_document_and_the_board_in_one_scripted_step(project, db_client: AsyncClient, agent_script) -> None:
    ada, base = await project()
    # One after the other: these tests share one database connection, which can't take two queries at once (in a
    # deployment each call has its own session; running calls together is covered in tests/unit/test_scripts.py).
    code = (
        f"doc = await read_file(file_path='/dotrix/{DOC}')\n"
        "issues = await list_issues()\n"
        "refunds = [i['key'] + ' ' + i['title'] for i in issues if 'efund' in i['title']]\n"
        "[doc['file_data']['content'].splitlines()[2], refunds]"
    )
    model = agent_script.say(tool_call("run_script", code=code), "Refunds go back to the zone they were paid in.")
    done = await _ask(db_client, base, ada.headers, "How do refunds work across zones?")
    assert done["status"] == "completed", done
    assert "run_script" in model.tools_received[0]
    assert "## Scripts" in str(model.received[0][0].content)
    result = str(model.received[1][-1].content)  # what the script handed back: only what it kept
    assert "A refund goes back to the zone it was paid in." in result and "KUN-1 Refund flow" in result
    assert "Zone picker" not in result and "Invoice footer" not in result and result.endswith("(2 tool calls)")

    # Each call the script made is in the run's activity, as an ordinary tool call's would be.
    events = (await db_client.get(f"{base}/agent/runs/{done['id']}/events", headers=ada.headers)).json()["events"]
    labels = [e["data"].get("label") for e in events if e["kind"] == "activity"]
    assert "Working through the project in one step" in labels
    assert f"Reading {DOC}" in labels and "Checking the board" in labels


async def test_a_script_can_only_read(project, db_client: AsyncClient, agent_script) -> None:
    ada, base = await project()
    model = agent_script.say(
        tool_call("run_script", code="await write_file(file_path='/dotrix/requirements/x.md', content='x')\n"
                                     "await create_issue(title='Sneaky')"),
        "I couldn't change anything from a script.",
    )
    done = await _ask(db_client, base, ada.headers, "Tidy up")
    assert done["status"] == "completed" and not done.get("approvals")
    assert "NameError" in str(model.received[1][-1].content)
    assert (await db_client.get(f"{base}/knowledge/files/requirements/x.md", headers=ada.headers)).status_code == 404
    issues = (await db_client.get(f"{base}/issues", headers=ada.headers)).json()
    assert "Sneaky" not in str(issues)


async def test_without_the_setting_nova_has_no_scripts(project, db_client: AsyncClient, agent_script) -> None:
    app = db_client._transport.app  # type: ignore[attr-defined]
    app.state.runner.settings = app.state.runner.settings.model_copy(update={"agent_scripts": False})
    ada, base = await project()
    model = agent_script.say("Nothing to script.")
    done = await _ask(db_client, base, ada.headers, "Hello")
    assert done["status"] == "completed"
    assert "run_script" not in model.tools_received[0] and "## Scripts" not in str(model.received[0][0].content)


@pytest.mark.parametrize("server_enabled", [False, True])
async def test_personal_code_mode_controls_new_deepagents_turns(project, db_client, agent_script, server_enabled):
    ada, base = await project()
    runner = db_client._transport.app.state.runner
    runner.settings = runner.settings.model_copy(update={"agent_scripts": server_enabled})
    for enabled in (False, True):
        saved = await db_client.put("/v1/me/code-mode", headers=ada.headers, json={"enabled": enabled})
        assert saved.status_code == 200
        model = agent_script.say("Here is the answer.")
        done = await _ask(db_client, base, ada.headers, "Hello")
        assert done["status"] == "completed", done
        assert ("run_script" in model.tools_received[0]) is (enabled and server_enabled)
        assert ("## Scripts" in str(model.received[0][0].content)) is (enabled and server_enabled)


@pytest.mark.parametrize("enabled", [False, True])
async def test_personal_preference_does_not_change_a_waiting_deepagents_turn(project, db_client, agent_script, enabled):
    ada, base = await project()
    runner = db_client._transport.app.state.runner
    runner.settings = runner.settings.model_copy(update={"agent_scripts": True})
    await db_client.put("/v1/me/code-mode", headers=ada.headers, json={"enabled": enabled})
    model = agent_script.say(tool_call("write_file", file_path="/dotrix/progress/plan.md", content="# Plan"), "Written.")
    done = await _ask(db_client, base, ada.headers, "Write the plan")
    assert done["status"] == "awaiting_approval", done
    await db_client.put("/v1/me/code-mode", headers=ada.headers, json={"enabled": not enabled})
    [approval] = done["approvals"]
    decided = await db_client.post(f"{base}/agent/runs/{done['id']}/decisions", headers=ada.headers, json={
        "decisions": [{"approval_id": approval["id"], "decision": "approve"}],
    })
    assert decided.status_code == 200, decided.text
    final = (await db_client.get(f"{base}/agent/runs/{done['id']}", headers=ada.headers)).json()
    assert final["status"] == "completed", final
    assert model.tools_received and all(("run_script" in tools) is enabled for tools in model.tools_received)
