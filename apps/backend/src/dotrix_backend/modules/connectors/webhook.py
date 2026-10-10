"""GitHub's webhook deliveries for the app: keep installations and connected repos current.

Only what GitHub signs with the app's webhook secret counts. A delivery names GitHub's ids
(installation, repo), which find the rows in whichever workspaces use them.
"""
from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.errors import Unauthorized
from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.auth.github import GitHubUnavailable
from dotrix_backend.modules.automations.events import record_event
from dotrix_backend.modules.automations.models import AutomationEvent

from .models import ConnectedRepo, GitHubInstallation


def verify_signature(settings: Settings, body: bytes, signature: str | None) -> None:
    """GitHub signs each delivery with the webhook secret (HMAC-SHA256 of the raw body)."""
    if settings.github_webhook_secret is None:
        raise GitHubUnavailable("GitHub webhooks aren't set up (set DOTRIX_GITHUB_WEBHOOK_SECRET in .env)")
    expected = "sha256=" + hmac.new(
        settings.github_webhook_secret.get_secret_value().encode(), body, hashlib.sha256
    ).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature):
        raise Unauthorized("The delivery isn't signed with the webhook secret")


async def handle(session: AsyncSession, event: str, payload: dict[str, Any]) -> tuple[str, list[uuid.UUID]]:
    """Apply one delivery; returns what was done (for the log and the response), and the
    projects whose default branch moved (their checkouts need a sync)."""
    if event == "push":
        return await _push(session, payload)
    if event == "installation":
        return await _installation(session, payload), []
    if event == "installation_repositories":
        return await _repositories(session, payload), []
    if event == "pull_request":
        return await _pull_request(session, payload), []
    return "ignored", []


async def _push(session: AsyncSession, payload: dict[str, Any]) -> tuple[str, list[uuid.UUID]]:
    """The default branch moved: remember its latest commit (and the repo's current name)."""
    repo = payload.get("repository") or {}
    repo_id, ref, after = repo.get("id"), payload.get("ref"), payload.get("after")
    if not repo_id or not after or ref != f"refs/heads/{repo.get('default_branch')}":
        return "ignored", []
    values: dict[str, Any] = {
        "last_push_sha": str(after)[:40], "last_push_at": datetime.now(UTC), "default_branch": str(repo["default_branch"]),
    }
    if repo.get("full_name"):
        values["full_name"] = str(repo["full_name"])
    result = await session.execute(
        update(ConnectedRepo).where(ConnectedRepo.github_repo_id == int(repo_id)).values(**values)
        .returning(ConnectedRepo.project_id, ConnectedRepo.workspace_id)
    )
    rows = list(result.all())
    head = payload.get("head_commit") or {}
    message = str(head.get("message") or "").strip().splitlines()[0][:150] if head.get("message") else ""
    for project_id, workspace_id in rows:
        await record_event(
            session, workspace_id=workspace_id, project_id=project_id, event=AutomationEvent.CODE_PUSHED,
            summary=f"Pushed to {repo['default_branch']} at {str(after)[:7]}" + (f": {message}" if message else ""),
            details={"sha": str(after)[:40], "branch": str(repo["default_branch"])},
        )
    await session.commit()
    return f"push: {len(rows)} connected", [project_id for project_id, _ in rows]


async def _installation(session: AsyncSession, payload: dict[str, Any]) -> str:
    """Uninstalled: forget it everywhere (its projects' repos are disconnected). Suspended or back."""
    installation_id = int((payload.get("installation") or {}).get("id") or 0)
    action = payload.get("action")
    rows = GitHubInstallation.installation_id == installation_id
    if action == "deleted":
        result = await session.execute(delete(GitHubInstallation).where(rows))
    elif action in ("suspend", "unsuspend"):
        result = await session.execute(
            update(GitHubInstallation).where(rows).values(suspended_at=datetime.now(UTC) if action == "suspend" else None)
        )
    else:
        return "ignored"
    await session.commit()
    return f"installation {action}: {result.rowcount}"


async def _repositories(session: AsyncSession, payload: dict[str, Any]) -> str:
    """Repos taken away from the installation: disconnect the projects that used them."""
    installation_id = int((payload.get("installation") or {}).get("id") or 0)
    removed = [int(r["id"]) for r in payload.get("repositories_removed") or [] if r.get("id")]
    if not removed:
        return "ignored"
    refs = select(GitHubInstallation.id).where(GitHubInstallation.installation_id == installation_id)
    result = await session.execute(
        delete(ConnectedRepo).where(ConnectedRepo.installation_ref.in_(refs), ConnectedRepo.github_repo_id.in_(removed))
    )
    await session.commit()
    return f"repositories removed: {result.rowcount} disconnected"


async def _pull_request(session: AsyncSession, payload: dict[str, Any]) -> str:
    """A coding session's PR was merged, closed, or reopened: record it on the session's turns and
    in its issue's log. The issue itself stays where it is: only a person closes it."""
    from dotrix_backend.modules.coding.models import CodingRun, PrState
    from dotrix_backend.modules.issues.models import IssueEvent, IssueEventKind

    action, pr = payload.get("action"), payload.get("pull_request") or {}
    repo_id, number = (payload.get("repository") or {}).get("id"), pr.get("number")
    if action not in ("closed", "reopened") or not repo_id or not number:
        return "ignored"
    state = PrState.OPEN if action == "reopened" else PrState.MERGED if pr.get("merged") else PrState.CLOSED
    projects = select(ConnectedRepo.project_id).where(ConnectedRepo.github_repo_id == int(repo_id))
    runs = list(await session.scalars(
        select(CodingRun).where(CodingRun.project_id.in_(projects), CodingRun.pr_number == int(number))
    ))
    if not runs:
        return "ignored"
    for run in runs:
        run.pr_state = state
    latest = max(runs, key=lambda r: r.turn)
    now = datetime.now(UTC)
    said = {PrState.MERGED: "merged", PrState.CLOSED: "closed without merging", PrState.OPEN: "reopened"}[state]
    session.add(IssueEvent(
        workspace_id=latest.workspace_id, issue_id=latest.issue_id, kind=IssueEventKind.UPDATED,
        author_agent=latest.agent.value, body=f"PR #{number} was {said} on GitHub", changes={}, created_at=now,
    ))
    await session.commit()
    return f"pull_request {action}: {len(runs)} coding runs"
