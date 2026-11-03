"""Human-reviewed, one-time GitHub Issues imports. Source text is data, never instructions."""
import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from dotrix_backend.core.errors import Conflict, Forbidden, NotFound
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.auth.models import OAuthAccount, User
from dotrix_backend.modules.issues.models import Issue, IssueStatus
from dotrix_backend.modules.issues.schemas import IssueCreate, Link
from dotrix_backend.modules.issues.service import IssueActor, IssueService
from dotrix_backend.modules.knowledge.models import AuthorType
from dotrix_backend.modules.projects.deps import ProjectAccess
from dotrix_backend.modules.projects.repository import ProjectRepository
from dotrix_backend.modules.workspaces.models import Membership, Role
from dotrix_backend.modules.workspaces.permissions import Permission, can

from .github_app import GitHubApp, GitHubUnavailable
from .import_models import GitHubImportedIssue, GitHubImportPreview
from .import_schemas import (
    GitHubImportConfirm,
    GitHubImportItem,
    GitHubImportPreviewCreate,
    GitHubImportPreviewRead,
    GitHubImportResult,
    GitHubImportResultItem,
)
from .models import ConnectedRepo, GitHubInstallation


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class GitHubIssueImport:
    def __init__(self, session: AsyncSession, github: GitHubApp):
        self.session, self.github = session, github

    async def _current(self, access):
        member = await self.session.scalar(select(Membership).options(joinedload(Membership.workspace)).where(
            Membership.workspace_id == access.project.workspace_id, Membership.user_id == access.member.user_id,
        ).with_for_update(of=Membership).execution_options(populate_existing=True))
        if member is None or not can(member, Permission.EDIT_ISSUES):
            raise Forbidden("You can no longer import issues")
        project = await ProjectRepository(self.session).visible(member, access.project.id)
        if project is None:
            raise NotFound("Project not found")
        return ProjectAccess(project, member)

    async def _binding(self, access: ProjectAccess, *, lock=False):
        statement = select(ConnectedRepo, GitHubInstallation).join(
            GitHubInstallation, ConnectedRepo.installation_ref == GitHubInstallation.id,
        ).where(ConnectedRepo.workspace_id == access.project.workspace_id,
                ConnectedRepo.project_id == access.project.id,
                GitHubInstallation.workspace_id == access.project.workspace_id,
        ).execution_options(populate_existing=True)
        if lock:
            statement = statement.with_for_update(of=(ConnectedRepo, GitHubInstallation))
        row = (await self.session.execute(statement)).first()
        if row is None:
            raise NotFound("Connect a repository to this project before importing issues")
        connected, installation = row
        if installation.suspended_at:
            raise Forbidden("The GitHub installation is suspended")
        return connected, installation

    async def _source(self, access, raw, repo, open_status):
        if (not isinstance(raw, dict) or type(raw.get("number")) is not int or type(raw.get("id")) is not int
                or not isinstance(raw.get("title", ""), str) or raw.get("body") is not None and not isinstance(raw["body"], str)
                or not isinstance(raw.get("labels", []), list) or not isinstance(raw.get("assignees", []), list)
                or any(not isinstance(a, dict) or type(a.get("id")) is not int for a in raw.get("assignees", []))):
            raise GitHubUnavailable("GitHub returned invalid issue data; load a new preview")
        number, source_id = int(raw["number"]), int(raw["id"])
        if number < 1 or source_id < 1 or "pull_request" in raw:
            raise Conflict("This source is not a GitHub issue")
        warnings = []
        title, body = str(raw.get("title") or "").strip(), str(raw.get("body") or "")
        blocked = not title or len(body) > 100_000 or raw.get("state") not in ("open", "closed")
        if blocked:
            warnings.append("This issue has unsupported content or state; it cannot be imported")
        if len(title) > 200:
            warnings.append("Title shortened to Dotrix's 200-character limit")
        labels = list(dict.fromkeys(str(x.get("name", "") if isinstance(x, dict) else x).strip() for x in raw.get("labels", [])))
        mapped_labels = list(dict.fromkeys(x[:64] for x in labels if x))[:30]
        if mapped_labels != labels:
            warnings.append("Some labels were omitted or shortened to Dotrix's limits")
        assignees = raw.get("assignees") or []
        assignee_id = assignee_name = None
        if len(assignees) == 1:
            linked = (await self.session.execute(select(Membership, User.display_name).join(
                OAuthAccount, OAuthAccount.user_id == Membership.user_id,
            ).join(User, User.id == Membership.user_id).where(
                Membership.workspace_id == access.project.workspace_id, Membership.role != Role.GUEST,
                OAuthAccount.provider == "github", OAuthAccount.provider_user_id == str(assignees[0]["id"]),
            ).execution_options(populate_existing=True))).first()
            if linked and await ProjectRepository(self.session).visible(linked[0], access.project.id):
                assignee_id, assignee_name = linked[0].user_id, linked[1]
            else:
                warnings.append("GitHub assignee has no verified, permitted Dotrix identity; left unassigned")
        elif assignees:
            warnings.append("Multiple GitHub assignees cannot map to one Dotrix assignee; left unassigned")
        if raw.get("state") == "closed" and raw.get("state_reason") not in (None, "completed"):
            blocked = True
            warnings.append("Closed without completion: no matching Dotrix state; excluded for manual review")
        if raw.get("milestone") or raw.get("type"):
            warnings.append("Milestones and GitHub issue types are not mapped; imports as a Task")
        item = GitHubImportItem(
            source_id=source_id, number=number, source_url=f"https://github.com/{repo.full_name}/issues/{number}",
            title=title[:200], description=body[:100_000], status="done" if raw.get("state") == "closed" else open_status,
            labels=mapped_labels, assignee_user_id=assignee_id, assignee_name=assignee_name,
            github_assignees=[str(a.get("login", ""))[:100] for a in assignees], warnings=warnings, blocked=blocked,
        )
        fingerprint = _digest({"item": item.model_dump(mode="json"), "updated_at": raw.get("updated_at")})
        return item, fingerprint

    async def _existing(self, access, repo_id, item):
        mapped = await self.session.scalar(select(GitHubImportedIssue).where(
            GitHubImportedIssue.workspace_id == access.project.workspace_id,
            GitHubImportedIssue.project_id == access.project.id, GitHubImportedIssue.github_repo_id == repo_id,
            GitHubImportedIssue.github_issue_id == item.source_id,
        ))
        if mapped:
            return mapped.issue_key, "already_imported" if mapped.issue_id else "deleted_task"
        linked = list(await self.session.scalars(select(Issue.key).where(
            Issue.workspace_id == access.project.workspace_id, Issue.project_id == access.project.id,
            Issue.links.contains([{"url": item.source_url}]),
        ).order_by(Issue.number)))
        if len(linked) > 1:
            item.warnings.append("Multiple Dotrix tasks already link this source; no new task will be created")
        return (linked[0], "already_linked") if linked else (None, None)

    async def preview(self, access: ProjectAccess, data: GitHubImportPreviewCreate) -> GitHubImportPreviewRead:
        connected, installation = await self._binding(access)
        binding_id, repo_id = connected.id, connected.github_repo_id
        repo = await self.github.repository(installation.installation_id, repo_id)
        token = await self.github.access_token(installation.installation_id, repository_id=repo_id, read_issues=True)
        raw, has_more = await self.github.issue_page(repo.full_name, token=token, page=data.page, state=data.state)
        await ProjectRepository(self.session).get(access.project.workspace_id, access.project.id, for_update=True)
        access = await self._current(access)
        current, _ = await self._binding(access, lock=True)
        if current.id != binding_id or current.github_repo_id != repo_id:
            raise Conflict("The connected repository changed; load a new preview")
        items, saved = [], []
        for source in raw:
            if "pull_request" in source:
                continue
            item, fingerprint = await self._source(access, source, repo, data.open_status)
            saved.append({"item": item.model_dump(mode="json"), "fingerprint": fingerprint})
            existing_key, existing_state = await self._existing(access, repo_id, item)
            item.existing_key = existing_key
            if existing_state == "deleted_task":
                item.blocked = True
                item.warnings.append("The previously imported task was deleted; it will not be recreated")
            items.append(item)
        # A connection change while GitHub answered must not publish a stale preview.
        current, _ = await self._binding(access)
        if current.id != binding_id or current.github_repo_id != repo_id:
            raise Conflict("The connected repository changed; load a new preview")
        now = datetime.now(UTC)
        pending = select(GitHubImportPreview.id).where(
            GitHubImportPreview.workspace_id == access.project.workspace_id, GitHubImportPreview.project_id == access.project.id,
            GitHubImportPreview.requested_by_id == access.member.user_id, GitHubImportPreview.result.is_(None),
        ).order_by(GitHubImportPreview.created_at.desc()).offset(4)
        await self.session.execute(delete(GitHubImportPreview).where(GitHubImportPreview.id.in_(pending)))
        row = GitHubImportPreview(
            workspace_id=access.project.workspace_id, project_id=access.project.id,
            requested_by_id=access.member.user_id, binding_id=binding_id, github_repo_id=repo_id,
            snapshot={"repository": repo.full_name, "open_status": data.open_status, "items": saved},
            expires_at=now + timedelta(minutes=30),
        )
        self.session.add(row)
        await self.session.commit()
        return GitHubImportPreviewRead(id=row.id, repository=repo.full_name, page=data.page, has_more=has_more,
                                      skipped_pull_requests=len(raw)-len(items), expires_at=row.expires_at, items=items)

    async def confirm(self, access: ProjectAccess, data: GitHubImportConfirm) -> GitHubImportResult:
        ids = sorted(set(data.issue_ids))
        selection = _digest(ids)
        row = await self.session.scalar(select(GitHubImportPreview).where(
            GitHubImportPreview.id == data.preview_id, GitHubImportPreview.workspace_id == access.project.workspace_id,
            GitHubImportPreview.project_id == access.project.id, GitHubImportPreview.requested_by_id == access.member.user_id,
        ))
        if row is None:
            raise NotFound("Import preview not found")
        if row.result is not None:
            if row.selection_digest != selection:
                raise Conflict("This preview was already imported with a different selection")
            return GitHubImportResult.model_validate(row.result)
        if row.expires_at <= datetime.now(UTC):
            raise Conflict("This preview expired; load a new preview")
        selected = [s for s in row.snapshot["items"] if s["item"]["source_id"] in ids]
        if len(selected) != len(ids) or any(s["item"]["blocked"] for s in selected):
            raise Conflict("Select only importable issues from this preview")
        binding_id, repo_id = row.binding_id, row.github_repo_id
        connected, installation = await self._binding(access)
        if connected.id != binding_id or connected.github_repo_id != repo_id:
            raise Conflict("The repository connection changed; load a new preview")
        try:
            async with asyncio.timeout(45):
                repo = await self.github.repository(installation.installation_id, repo_id)
                token = await self.github.access_token(installation.installation_id, repository_id=repo_id, read_issues=True)
                pending = []
                for saved in selected:
                    item = GitHubImportItem.model_validate(saved["item"])
                    if not (await self._existing(access, repo_id, item))[0]:
                        pending.append(item)
                limit = asyncio.Semaphore(4)
                async def fetch(item):
                    async with limit:
                        return item.source_id, await self.github.read_issue(repo.full_name, item.number, token=token)
                responses = await asyncio.gather(*(fetch(item) for item in pending), return_exceptions=True)
                for response in responses:
                    if isinstance(response, BaseException):
                        raise response
                fresh = dict(responses)
                for saved in selected:
                    item = GitHubImportItem.model_validate(saved["item"])
                    if item.source_id not in fresh:
                        continue
                    _, fingerprint = await self._source(access, fresh[item.source_id], repo, row.snapshot["open_status"])
                    if fingerprint != saved["fingerprint"]:
                        raise Conflict("A GitHub issue or assignee mapping changed; review a new preview before importing")
                await self.github.repository(installation.installation_id, repo_id)
        except TimeoutError as exc:
            raise GitHubUnavailable("GitHub verification timed out; no tasks were imported. Retry this preview") from exc
        # Serialize the entire local import only after source verification succeeds.
        project = await ProjectRepository(self.session).get(access.project.workspace_id, access.project.id, for_update=True)
        access = await self._current(access)
        member, project = access.member, access.project
        connected, _ = await self._binding(access, lock=True)
        row = await self.session.scalar(select(GitHubImportPreview).where(
            GitHubImportPreview.id == data.preview_id, GitHubImportPreview.workspace_id == project.workspace_id,
            GitHubImportPreview.project_id == project.id,
        ).with_for_update().execution_options(populate_existing=True))
        if row is None or connected.id != binding_id or connected.github_repo_id != repo_id:
            raise Conflict("The repository connection changed; load a new preview")
        if row.result is not None:
            if row.selection_digest != selection:
                raise Conflict("This preview was already imported with a different selection")
            return GitHubImportResult.model_validate(row.result)
        if row.expires_at <= datetime.now(UTC):
            raise Conflict("This preview expired; load a new preview")
        result = []
        for saved in selected:
            item = GitHubImportItem.model_validate(saved["item"])
            existing_key, outcome = await self._existing(access, repo_id, item)
            if existing_key:
                result.append(GitHubImportResultItem(source_id=item.source_id, issue_key=existing_key, outcome=outcome))
                continue
            if item.source_id not in fresh:
                raise Conflict("A linked Dotrix task changed during verification; retry this preview")
            _, fingerprint = await self._source(access, fresh[item.source_id], repo, row.snapshot["open_status"])
            if fingerprint != saved["fingerprint"]:
                raise Conflict("An assignee mapping changed; review a new preview")
            issue = await IssueService(self.session)._insert(project, IssueActor(member), IssueCreate(
                title=item.title, description=item.description, status=IssueStatus(item.status), labels=item.labels,
                assignee_user_id=item.assignee_user_id,
                links=[Link(kind="other", url=item.source_url, title=f"GitHub #{item.number}")],
            ))
            self.session.add(GitHubImportedIssue(
                workspace_id=project.workspace_id, project_id=project.id, github_repo_id=repo_id,
                github_issue_id=item.source_id, source_number=item.number, source_url=item.source_url,
                issue_id=issue.id, issue_key=issue.key, imported_by_id=member.user_id,
            ))
            result.append(GitHubImportResultItem(source_id=item.source_id, issue_key=issue.key, outcome="created"))
        final = GitHubImportResult(items=result)
        row.selection_digest, row.result = selection, final.model_dump(mode="json")
        AuditLog(self.session).record(workspace_id=project.workspace_id, project_id=project.id,
                                      action="github.issues_imported", target=str(row.id), actor_type=AuthorType.USER,
                                      actor_user_id=member.user_id, details={"repository_id": repo_id, "items": row.result["items"]})
        await self.session.commit()
        return final


async def cleanup_import_previews(session: AsyncSession, now: datetime) -> int:
    result = await session.execute(delete(GitHubImportPreview).where(or_(
        (GitHubImportPreview.result.is_(None)) & (GitHubImportPreview.expires_at < now),
        GitHubImportPreview.created_at < now - timedelta(days=7),
    )))
    return result.rowcount
