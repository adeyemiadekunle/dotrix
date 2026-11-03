"""Only already-published code evidence is shared; coding and Chat transcripts stay private."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from dotrix_backend.modules.coding.models import CodingAgent, CodingRun, CodingRunStatus, PrState
from dotrix_backend.modules.workspaces.models import Role


@pytest.fixture
def shared_code(db_client, signup, create_team, add_member, db_session):
    async def make():
        owner = await signup()
        colleague = await signup(email="colleague@example.com", name="Colleague")
        outsider = await signup(email="outsider@example.com", name="Outsider")
        team = await create_team(owner.headers)
        await add_member(team["id"], colleague.id, Role.MEMBER)
        ws = f"/v1/workspaces/{team['id']}"
        project = (await db_client.post(f"{ws}/projects", headers=owner.headers, json={"key": "CODE", "name": "Shared code"})).json()
        base = f"{ws}/projects/{project['id']}"
        issue = (await db_client.post(f"{base}/issues", headers=owner.headers, json={"title": "Agreed scope", "description": "Shared rationale and acceptance"})).json()
        run_id = uuid.uuid4()
        run = CodingRun(
            id=run_id, session_id=run_id, workspace_id=uuid.UUID(team["id"]), project_id=uuid.UUID(project["id"]),
            issue_id=uuid.UUID(issue["id"]), issue_key=issue["key"], agent=CodingAgent.FX,
            requested_by_id=uuid.UUID(owner.id), status=CodingRunStatus.PR_OPENED,
            brief="PRIVATE BRIEF", summary="PRIVATE DIAGNOSTIC", events=[{"text": "PRIVATE EVENT"}],
            repo_full_name="acme/app", base_branch="main", created_at=datetime.now(UTC),
            pr_number=17, pr_url="https://github.com/acme/app/pull/17", pr_state=PrState.OPEN,
            commit_sha="a" * 40, ci_sha="a" * 40, ci_state="passed",
            review_posted_url="https://github.com/acme/app/pull/17#pullrequestreview-1",
        )
        db_session.add(run)
        await db_session.commit()
        return owner, colleague, outsider, base, issue, run
    return make


async def test_shared_evidence_does_not_grant_private_session_or_review_access(db_client, shared_code):
    owner, colleague, outsider, base, issue, run = await shared_code()
    url = f"{base}/coding/issues/{issue['key']}/outcomes"
    response = await db_client.get(url, headers=colleague.headers)
    assert response.status_code == 200, response.text
    [outcome] = response.json()
    assert outcome == {
        "pr_number": 17, "pr_url": run.pr_url, "pr_state": "open", "commit_sha": "a" * 40,
        "turn": 1, "finished_at": None, "ci_state": "passed", "review_url": run.review_posted_url,
        "ci_review_url": None, "session_id": None,
    }
    assert "PRIVATE" not in response.text and "thread" not in response.text and "fx" not in response.text
    assert (await db_client.get(f"{base}/coding/runs/{run.id}", headers=colleague.headers)).status_code == 404
    assert (await db_client.get(url, headers=outsider.headers)).status_code == 404
    assert (await db_client.get(url, headers=owner.headers)).json()[0]["session_id"] == str(run.session_id)
    assert (await db_client.get(f"{base}/coding/issues/CODE-999/outcomes", headers=owner.headers)).status_code == 404
    other = (await db_client.post(base.rsplit("/", 1)[0], headers=owner.headers, json={"key": "NEXT", "name": "Other"})).json()
    other_base = base.rsplit("/", 1)[0] + "/" + other["id"]
    other_issue = (await db_client.post(f"{other_base}/issues", headers=owner.headers, json={"title": "Other work"})).json()
    assert (await db_client.get(f"{other_base}/coding/issues/{other_issue['key']}/outcomes", headers=owner.headers)).json() == []


async def test_unpublished_followups_and_stale_checks_do_not_replace_published_evidence(db_client, shared_code, db_session):
    owner, colleague, _, base, issue, run = await shared_code()
    next_id = uuid.uuid4()
    follow = CodingRun(
        id=next_id, session_id=run.session_id, turn=2, workspace_id=run.workspace_id, project_id=run.project_id,
        issue_id=run.issue_id, issue_key=run.issue_key, agent=run.agent, requested_by_id=run.requested_by_id,
        status=CodingRunStatus.CHANGES_READY, brief="PRIVATE FOLLOWUP", repo_full_name=run.repo_full_name,
        base_branch="main", created_at=run.created_at + timedelta(seconds=1),
        pr_number=17, pr_url=run.pr_url, pr_state=PrState.OPEN, commit_sha="b" * 40,
        ci_state="passed", ci_sha="a" * 40, ci_review_posted_url="https://github.com/acme/app/pull/17#old-ci",
    )
    db_session.add(follow)
    await db_session.commit()
    url = f"{base}/coding/issues/{issue['key']}/outcomes"
    [outcome] = (await db_client.get(url, headers=colleague.headers)).json()
    assert outcome["turn"] == 1 and outcome["commit_sha"] == "a" * 40
    follow.status = CodingRunStatus.PR_OPENED
    await db_session.commit()
    [outcome] = (await db_client.get(url, headers=colleague.headers)).json()
    assert outcome["turn"] == 2 and outcome["commit_sha"] == "b" * 40
    assert outcome["ci_state"] is None and outcome["ci_review_url"] is None and outcome["review_url"] is None
    follow.pr_state = PrState.MERGED
    await db_session.commit()
    assert (await db_client.get(url, headers=colleague.headers)).json()[0]["pr_state"] == "merged"
    assert (await db_client.get(f"{base}/issues/{issue['key']}", headers=owner.headers)).json()["status"] == "todo"


@pytest.mark.parametrize("field", ["review_posted_url", "ci_review_posted_url"])
async def test_posting_review_claims_are_not_shared_as_urls(db_client, shared_code, db_session, field):
    _, colleague, _, base, issue, run = await shared_code()
    setattr(run, field, "posting")
    await db_session.commit()  # the worker's durable claim survives a crash
    url = f"{base}/coding/issues/{issue['key']}/outcomes"
    [outcome] = (await db_client.get(url, headers=colleague.headers)).json()
    shared_field = "review_url" if field == "review_posted_url" else "ci_review_url"
    assert outcome[shared_field] is None
    assert "posting" not in str(outcome)
    if field == "ci_review_posted_url":
        assert outcome["review_url"] == run.review_posted_url
    posted = "https://github.com/acme/app/pull/17#issuecomment-123"
    setattr(run, field, posted)
    await db_session.commit()
    [outcome] = (await db_client.get(url, headers=colleague.headers)).json()
    assert outcome[shared_field] == posted


async def test_teammate_can_follow_published_scope_to_code_without_private_chat(db_client, shared_code, agent_script):
    owner, colleague, _, base, issue, _ = await shared_code()
    await db_client.patch(f"{base}/issues/{issue['key']}", headers=owner.headers, json={"status": "review"})
    agent_script.say("PRIVATE conversation rationale, not automatically shared")
    run = (await db_client.post(f"{base}/agent/runs", headers=owner.headers, json={"message": "Discuss scope"})).json()
    saved = await db_client.post(f"{base}/agent/runs/{run['id']}/publications", headers=owner.headers, json={
        "request_id": str(uuid.uuid4()), "destination": "requirements", "title": "Agreed scope",
        "content": "Shared acceptance and rationale selected by a person.", "acknowledge_shared": True,
        "related_issue": issue["key"],
    })
    assert saved.status_code == 200, saved.text
    path = saved.json()["target"]
    document = (await db_client.get(f"{base}/knowledge/files/{path}", headers=colleague.headers)).json()
    assert "Shared acceptance and rationale" in document["content"] and "PRIVATE" not in document["content"]
    links = (await db_client.get(f"{base}/graph/neighbors", headers=colleague.headers, params={"ref": path})).json()["links"]
    assert any(link["node"]["ref"] == issue["key"] for link in links)
    [outcome] = (await db_client.get(f"{base}/coding/issues/{issue['key']}/outcomes", headers=colleague.headers)).json()
    assert outcome["pr_number"] == 17 and outcome["review_url"] and outcome["session_id"] is None
    assert (await db_client.get(f"{base}/agent/runs/{run['id']}", headers=colleague.headers)).status_code == 404
    assert (await db_client.get(f"{base}/issues/{issue['key']}", headers=colleague.headers)).json()["status"] == "review"
