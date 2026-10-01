"""A project's activity: what people and agents did, newest first, from the records each module
already keeps (issue logs, document versions, agent runs, approval decisions). Nothing new is
stored; the audit log stays the strict record for owners and admins."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.modules.agents.models import AgentApproval, AgentRun, ApprovalStatus
from pmagent_backend.modules.issues.models import Issue, IssueEvent
from pmagent_backend.modules.knowledge.models import AuthorType, KnowledgeFile, KnowledgeVersion
from pmagent_backend.modules.projects.deps import ProjectAccess
from pmagent_backend.modules.workspaces.permissions import Permission, can

from .schemas import ActivityItem, ActivityKind

ISSUE_KINDS = {
    "created": ActivityKind.ISSUE_CREATED,
    "updated": ActivityKind.ISSUE_UPDATED,
    "commented": ActivityKind.ISSUE_COMMENTED,
    "claimed": ActivityKind.ISSUE_CLAIMED,
}


class ActivityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def project(self, access: ProjectAccess, *, before: datetime | None, limit: int) -> list[ActivityItem]:
        """The newest `limit` items older than `before`. Each source gives at most `limit`, so
        merging them and cutting at `limit` is exact."""
        project_id = access.project.id
        items: list[ActivityItem] = []

        events = (
            select(IssueEvent, Issue.key, Issue.title)
            .join(Issue, Issue.id == IssueEvent.issue_id)
            .where(Issue.project_id == project_id, IssueEvent.workspace_id == access.member.workspace_id)
        )
        if before is not None:
            events = events.where(IssueEvent.created_at < before)
        for event, key, title in await self.session.execute(
            events.order_by(IssueEvent.created_at.desc()).limit(limit)
        ):
            items.append(
                ActivityItem(
                    kind=ISSUE_KINDS[event.kind.value],
                    at=event.created_at,
                    actor_user_id=event.author_user_id,
                    actor_agent=event.author_agent,
                    issue_key=key,
                    issue_title=title,
                    changes=event.changes or {},
                    body=event.body,
                )
            )

        versions = (
            select(KnowledgeVersion, KnowledgeFile.path)
            .join(KnowledgeFile, KnowledgeFile.id == KnowledgeVersion.file_id)
            .where(
                KnowledgeVersion.project_id == project_id,
                KnowledgeVersion.author_type != AuthorType.SYSTEM,  # the skeleton isn't anyone's act
            )
        )
        if before is not None:
            versions = versions.where(KnowledgeVersion.created_at < before)
        for version, path in await self.session.execute(
            versions.order_by(KnowledgeVersion.created_at.desc()).limit(limit)
        ):
            by_agent = version.author_type is AuthorType.AGENT
            items.append(
                ActivityItem(
                    kind=ActivityKind.DOCUMENT_DELETED if version.deleted else ActivityKind.DOCUMENT_CHANGED,
                    at=version.created_at,
                    actor_user_id=None if by_agent else version.author_id,
                    actor_agent=version.agent if by_agent else None,
                    path=path,
                    version=version.version,
                    body=version.message,
                    instructed_by_id=version.instructed_by_id,
                    approved_by_id=version.approved_by_id,
                )
            )

        # Conversations and decisions are for people who can chat with the agents here.
        if can(access.member, Permission.CHAT):
            runs = select(AgentRun).where(AgentRun.project_id == project_id)
            if before is not None:
                runs = runs.where(AgentRun.created_at < before)
            for run in await self.session.scalars(runs.order_by(AgentRun.created_at.desc()).limit(limit)):
                items.append(
                    ActivityItem(
                        kind=ActivityKind.RUN_STARTED,
                        at=run.created_at,
                        actor_user_id=run.requested_by_id,
                        actor_agent=None,
                        body=run.title or run.message,
                        run_id=run.id,
                        run_kind=run.kind.value,
                        run_status=run.status.value,
                    )
                )

            decided = select(AgentApproval).where(
                AgentApproval.project_id == project_id,
                AgentApproval.status != ApprovalStatus.PENDING,
                AgentApproval.decided_by_id.is_not(None),  # rejected automatically: not a person's act
                AgentApproval.decided_at.is_not(None),
            )
            if before is not None:
                decided = decided.where(AgentApproval.decided_at < before)
            for approval in await self.session.scalars(
                decided.order_by(AgentApproval.decided_at.desc()).limit(limit)
            ):
                assert approval.decided_at is not None
                items.append(
                    ActivityItem(
                        kind=ActivityKind.APPROVAL_DECIDED,
                        at=approval.decided_at,
                        actor_user_id=approval.decided_by_id,
                        actor_agent=None,
                        run_id=approval.run_id,
                        tool=approval.tool,
                        target=approval.target,
                        decision=approval.status.value,
                        reason=approval.reason,
                    )
                )

        items.sort(key=lambda item: item.at, reverse=True)
        return items[:limit]
