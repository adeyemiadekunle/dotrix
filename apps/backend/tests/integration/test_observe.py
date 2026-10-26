"""The Admin screen's observability reads: a workspace's health overview and its unified run
history (chat and coding), under the same privacy as the runs themselves."""
import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.modules.agents.models import AgentRun, RunKind, RunStatus
from dotrix_backend.modules.coding.models import (
    CodingAgent,
    CodingLocation,
    CodingRun,
    CodingRunStatus,
)
from dotrix_backend.modules.execution.models import RunDispatch
from dotrix_backend.modules.workspaces.models import Role


def _chat_run(ws: str, project: str, ada, **kw) -> AgentRun:
    now = datetime.now(UTC)
    return AgentRun(
        workspace_id=uuid.UUID(ws),
        project_id=uuid.UUID(project),
        thread_id=uuid.uuid4(),
        kind=RunKind.CHAT,
        status=kw.pop("status", RunStatus.COMPLETED),
        message=kw.pop("message", "hello"),
        title=kw.pop("title", None),
        requested_by_id=uuid.UUID(ada.id),
        created_at=kw.pop("created_at", now),
        updated_at=kw.pop("updated_at", now),
        **kw,
    )


def _coding_run(ws: str, project: str, issue: str, ada, **kw) -> CodingRun:
    now = datetime.now(UTC)
    return CodingRun(
        workspace_id=uuid.UUID(ws),
        project_id=uuid.UUID(project),
        issue_id=uuid.UUID(issue),
        issue_key=kw.pop("issue_key", "KUN-1"),
        session_id=uuid.uuid4(),
        agent=kw.pop("agent", CodingAgent.CLAUDE_CODE),
        status=kw.pop("status", CodingRunStatus.PR_OPENED),
        brief="Do the thing",
        repo_full_name="kunemi/api",
        base_branch="main",
        location=kw.pop("location", CodingLocation.CLOUD),
        requested_by_id=uuid.UUID(ada.id),
        created_at=kw.pop("created_at", now),
        **kw,
    )


async def _personal_ws(db_client: AsyncClient, headers: dict[str, str]) -> dict:
    listed = (await db_client.get("/v1/workspaces", headers=headers)).json()
    return next(w for w in listed if w["kind"] == "personal")


async def test_the_overview_counts_the_workspaces_health(signup, db_client: AsyncClient, db_session: AsyncSession) -> None:
    ada = await signup()
    ws = await _personal_ws(db_client, ada.headers)
    base = f"/v1/workspaces/{ws['id']}"
    project = (
        await db_client.post(f"{base}/projects", json={"key": "KUN", "name": "Kunemi"}, headers=ada.headers)
    ).json()
    issue = (await db_client.post(f"{base}/projects/{project['id']}/issues", json={"title": "Refunds"}, headers=ada.headers)).json()

    overview = (await db_client.get(f"{base}/observe/overview", headers=ada.headers)).json()
    assert overview["jobs"] in ("local", "worker", "inline")
    assert overview["counts"]["projects"] == 1 and overview["counts"]["members"] == 1
    assert overview["chat"] == {
        "total": 0, "active": 0, "waiting": 0, "failed_7d": 0,
        "input_tokens_7d": 0, "output_tokens_7d": 0, "model_calls_7d": 0, "cost_usd_7d": None,
    }
    assert overview["queue"] == {"pending": 0, "oldest_pending_seconds": None, "discarded_7d": 0}
    assert overview["stuck"] == 0 and "limits" not in overview

    # A finished chat run and a coding turn are counted, by kind.
    db_session.add(_chat_run(ws["id"], project["id"], ada, input_tokens=10, output_tokens=5, model_calls=2))
    db_session.add(_coding_run(ws["id"], project["id"], issue["id"], ada, input_tokens=20, output_tokens=7, cost_usd=0.04))
    # And a chat run stuck on a lapsed lease reads as stuck, not active.
    db_session.add(
        _chat_run(
            ws["id"], project["id"], ada,
            status=RunStatus.RUNNING, lease_expires_at=datetime.now(UTC) - timedelta(minutes=5),
        )
    )
    await db_session.commit()

    overview = (await db_client.get(f"{base}/observe/overview", headers=ada.headers)).json()
    assert overview["chat"]["total"] == 2 and overview["chat"]["active"] == 1
    assert overview["chat"]["input_tokens_7d"] == 10 and overview["chat"]["model_calls_7d"] == 2
    assert overview["coding"]["total"] == 1 and overview["coding"]["cost_usd_7d"] == 0.04
    assert overview["stuck"] == 1


async def test_the_runs_list_merges_chat_and_coding_newest_first(
    signup, db_client: AsyncClient, db_session: AsyncSession
) -> None:
    ada = await signup()
    ws = await _personal_ws(db_client, ada.headers)
    base = f"/v1/workspaces/{ws['id']}"
    project = (
        await db_client.post(f"{base}/projects", json={"key": "KUN", "name": "Kunemi"}, headers=ada.headers)
    ).json()
    issue = (await db_client.post(f"{base}/projects/{project['id']}/issues", json={"title": "Refunds"}, headers=ada.headers)).json()
    now = datetime.now(UTC)

    db_session.add(_chat_run(ws["id"], project["id"], ada, title="Ask about refunds", created_at=now - timedelta(hours=2)))
    db_session.add(
        _coding_run(
            ws["id"], project["id"], issue["id"], ada, issue_key=issue["key"],
            status=CodingRunStatus.FAILED, error="the sandbox died",
            created_at=now - timedelta(hours=1), location=CodingLocation.LOCAL,
        )
    )
    db_session.add(_chat_run(ws["id"], project["id"], ada, title="Newer question", created_at=now))
    await db_session.commit()

    runs = (await db_client.get(f"{base}/observe/runs", headers=ada.headers)).json()
    assert [r["kind"] for r in runs] == ["chat", "coding", "chat"]
    assert runs[0]["label"] == "Newer question"
    assert runs[1]["label"] == issue["key"] and runs[1]["status"] == "failed" and runs[1]["location"] == "local"
    assert runs[1]["error"] == "the sandbox died"

    # Kind filter and paging.
    coding = (await db_client.get(f"{base}/observe/runs", params={"kind": "coding"}, headers=ada.headers)).json()
    assert [r["kind"] for r in coding] == ["coding"]
    older = (
        await db_client.get(
            f"{base}/observe/runs", params={"before": runs[1]["created_at"]}, headers=ada.headers
        )
    ).json()
    assert [r["label"] for r in older] == ["Ask about refunds"]


async def test_a_member_without_usage_rights_gets_none(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    team = await create_team(ada.headers)
    await add_member(team["id"], bob.id, Role.MEMBER)
    base = f"/v1/workspaces/{team['id']}"

    for path in ("observe/overview", "observe/runs"):
        assert (await db_client.get(f"{base}/{path}", headers=bob.headers)).status_code == 403
    assert (await db_client.get(f"{base}/observe/overview", headers=ada.headers)).status_code == 200


async def test_queue_excludes_other_peoples_private_dispatches(
    signup, create_team, add_member, db_client: AsyncClient, db_session: AsyncSession
) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    team = await create_team(ada.headers)
    await add_member(team["id"], bob.id, Role.MEMBER)
    base = f"/v1/workspaces/{team['id']}"
    project = (await db_client.post(f"{base}/projects", json={"key": "KUN", "name": "Kunemi"}, headers=ada.headers)).json()
    issue = (await db_client.post(f"{base}/projects/{project['id']}/issues", json={"title": "Task"}, headers=ada.headers)).json()
    private_chat = _chat_run(team["id"], project["id"], bob, status=RunStatus.QUEUED)
    private_coding = _coding_run(team["id"], project["id"], issue["id"], bob, status=CodingRunStatus.QUEUED)
    own_chat = _chat_run(team["id"], project["id"], ada, status=RunStatus.QUEUED)
    db_session.add_all([private_chat, private_coding, own_chat])
    await db_session.flush()
    now = datetime.now(UTC)
    db_session.add_all([
        RunDispatch(
            workspace_id=uuid.UUID(team["id"]), agent_run_id=private_chat.id, generation=1,
            queue_name="chat", payload={}, created_at=now - timedelta(hours=2), next_attempt_at=now,
        ),
        RunDispatch(
            workspace_id=uuid.UUID(team["id"]), coding_run_id=private_coding.id, generation=1,
            queue_name="coding", payload={}, created_at=now - timedelta(hours=1), next_attempt_at=now,
            discarded_at=now,
        ),
        RunDispatch(
            workspace_id=uuid.UUID(team["id"]), agent_run_id=own_chat.id, generation=1,
            queue_name="chat", payload={}, created_at=now - timedelta(minutes=1), next_attempt_at=now,
        ),
    ])
    await db_session.commit()

    overview = (await db_client.get(f"{base}/observe/overview", headers=ada.headers)).json()
    assert overview["queue"]["pending"] == 1
    assert overview["queue"]["discarded_7d"] == 0
    assert overview["queue"]["oldest_pending_seconds"] < 300
    assert overview["chat"]["total"] == 1
