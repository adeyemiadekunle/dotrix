"""Published code metadata for the shared task; private coding sessions stay private."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from dotrix_backend.modules.issues.service import IssueService
from dotrix_backend.modules.projects.deps import ProjectAccess

from .models import CodingRun, CodingRunStatus
from .schemas import SharedCodingOutcomeRead
from .service import _posted


async def shared_outcomes(session: AsyncSession, access: ProjectAccess, key: str) -> list[SharedCodingOutcomeRead]:
    issue = await IssueService(session).get(access.project, key)
    rows = await session.scalars(select(CodingRun).options(load_only(
        CodingRun.id, CodingRun.workspace_id, CodingRun.project_id, CodingRun.issue_id,
        CodingRun.requested_by_id, CodingRun.session_id, CodingRun.turn,
        CodingRun.pr_number, CodingRun.pr_url, CodingRun.pr_state, CodingRun.commit_sha,
        CodingRun.ci_state, CodingRun.ci_sha, CodingRun.review_posted_url, CodingRun.ci_review_posted_url,
        CodingRun.finished_at,
    )).where(
        CodingRun.workspace_id == access.project.workspace_id, CodingRun.project_id == access.project.id,
        CodingRun.issue_id == issue.id, CodingRun.status == CodingRunStatus.PR_OPENED,
        CodingRun.pr_number.is_not(None), CodingRun.pr_url.is_not(None),
    ).order_by(CodingRun.created_at.desc(), CodingRun.turn.desc(), CodingRun.id.desc()).limit(100))
    result, seen = [], set()
    for run in rows:
        # Show the latest published turn of each PR; an unpublished follow-up must
        # not replace its evidence or expose its private brief/diagnostics.
        if run.pr_url in seen:
            continue
        seen.add(run.pr_url)
        current_ci = bool(run.commit_sha and run.ci_sha == run.commit_sha)
        result.append(SharedCodingOutcomeRead(
            pr_number=run.pr_number, pr_url=run.pr_url, pr_state=run.pr_state,
            commit_sha=run.commit_sha, turn=run.turn, finished_at=run.finished_at,
            ci_state=run.ci_state if current_ci else None,
            review_url=_posted(run.review_posted_url),
            ci_review_url=_posted(run.ci_review_posted_url) if current_ci else None,
            # Only the requester can open a published coding session. Never
            # include a Chat thread or a private Juno run in shared metadata.
            session_id=run.session_id if run.requested_by_id == access.member.user_id else None,
        ))
    return result
