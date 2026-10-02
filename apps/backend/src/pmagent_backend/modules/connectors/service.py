"""Connecting a workspace to GitHub (the app's installations) and each project to its repo."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core.errors import Conflict, Forbidden, NotFound
from pmagent_backend.modules.audit.service import AuditLog
from pmagent_backend.modules.auth.github import GitHubClient
from pmagent_backend.modules.knowledge.models import AuthorType
from pmagent_backend.modules.projects.deps import ProjectAccess
from pmagent_backend.modules.projects.models import Project
from pmagent_backend.modules.projects.repo_urls import normalize_repo_url
from pmagent_backend.modules.workspaces.models import Membership

from .github_app import GitHubApp
from .models import ConnectedRepo, GitHubInstallation
from .schemas import (
    ConnectedRepoRead,
    GitHubStatus,
    InstallationAdd,
    InstallationRead,
    RepoConnect,
    RepoOption,
)


class RepoTaken(Conflict):
    code = "repo_taken"


def _now() -> datetime:
    return datetime.now(UTC)


def _installation(row: GitHubInstallation) -> InstallationRead:
    return InstallationRead(
        id=row.id, installation_id=row.installation_id, account_login=row.account_login,
        account_type=row.account_type, suspended=row.suspended_at is not None, created_at=row.created_at,
    )


class ConnectorService:
    def __init__(self, session: AsyncSession, app: GitHubApp) -> None:
        self.session = session
        self.app = app

    # -- the workspace's installations -----------------------------------------------

    async def status(self, member: Membership) -> GitHubStatus:
        rows = await self._installations(member.workspace_id)
        return GitHubStatus(
            configured=self.app.configured,
            install_url=self.app.install_url() if self.app.configured else None,
            installations=[_installation(r) for r in rows],
        )

    async def add_installation(self, member: Membership, data: InstallationAdd, oauth: GitHubClient) -> InstallationRead:
        """Add an installation of the app to this workspace, once GitHub confirms the person can
        manage it. Adding it again refreshes its account details."""
        if data.installation_id not in await oauth.installation_ids(data.code):
            raise Forbidden("GitHub says you can't manage that installation of the app")
        found = await self.app.installation(data.installation_id)
        row = await self.session.scalar(
            select(GitHubInstallation).where(
                GitHubInstallation.workspace_id == member.workspace_id,
                GitHubInstallation.installation_id == found.id,
            )
        )
        if row is None:
            row = GitHubInstallation(
                workspace_id=member.workspace_id, installation_id=found.id, installed_by_id=member.user_id,
                account_login=found.account_login, account_type=found.account_type, created_at=_now(),
            )
            self.session.add(row)
            AuditLog(self.session).record(
                workspace_id=member.workspace_id, action="github.installation_added", target=found.account_login,
                actor_type=AuthorType.USER, actor_user_id=member.user_id,
                details={"installation_id": found.id, "account_type": found.account_type},
            )
        row.account_login, row.account_type = found.account_login, found.account_type
        row.suspended_at = _now() if found.suspended else None
        await self.session.commit()
        return _installation(row)

    async def remove_installation(self, member: Membership, installation_ref: uuid.UUID) -> None:
        """Forget an installation here; its projects' repos are disconnected. (It stays installed
        on GitHub: uninstall it there to take the app's access away.)"""
        row = await self._installation_row(member.workspace_id, installation_ref)
        AuditLog(self.session).record(
            workspace_id=member.workspace_id, action="github.installation_removed", target=row.account_login,
            actor_type=AuthorType.USER, actor_user_id=member.user_id, details={"installation_id": row.installation_id},
        )
        await self.session.delete(row)
        await self.session.commit()

    async def repos(self, member: Membership) -> list[RepoOption]:
        """Every repo the workspace's installations can see, with the project using each."""
        used = {
            repo_id: key
            for repo_id, key in await self.session.execute(
                select(ConnectedRepo.github_repo_id, Project.key)
                .join(Project, Project.id == ConnectedRepo.project_id)
                .where(ConnectedRepo.workspace_id == member.workspace_id)
            )
        }
        options: list[RepoOption] = []
        for row in await self._installations(member.workspace_id):
            if row.suspended_at is not None:
                continue
            try:
                found = await self.app.repositories(row.installation_id)
            except NotFound:  # uninstalled on GitHub since; the webhook will tidy up
                continue
            options += [
                RepoOption(
                    installation_ref=row.id, github_repo_id=r.id, full_name=r.full_name, private=r.private,
                    default_branch=r.default_branch, html_url=r.html_url, project_key=used.get(r.id),
                )
                for r in found
            ]
        return sorted(options, key=lambda o: o.full_name.lower())

    # -- a project's repo --------------------------------------------------------------

    async def connected(self, access: ProjectAccess) -> ConnectedRepoRead | None:
        row = await self.session.execute(
            select(ConnectedRepo, GitHubInstallation.account_login)
            .join(GitHubInstallation, GitHubInstallation.id == ConnectedRepo.installation_ref)
            .where(ConnectedRepo.project_id == access.project.id, ConnectedRepo.workspace_id == access.project.workspace_id)
        )
        found = row.first()
        if found is None:
            return None
        repo, account = found
        return ConnectedRepoRead(
            full_name=repo.full_name, html_url=repo.html_url, private=repo.private, default_branch=repo.default_branch,
            account_login=account, connected_at=repo.connected_at, connected_by_id=repo.connected_by_id,
            last_push_sha=repo.last_push_sha, last_push_at=repo.last_push_at,
        )

    async def connect(self, access: ProjectAccess, data: RepoConnect) -> ConnectedRepoRead:
        """Connect the project to a repo one of the workspace's installations can see, replacing
        any repo it had. The project's repo address follows, so `pmagent connect` finds it."""
        project, member = access.project, access.member
        installation = await self._installation_row(project.workspace_id, data.installation_ref)
        repo = await self.app.repository(installation.installation_id, data.github_repo_id)
        other = await self.session.scalar(
            select(Project.key)
            .join(ConnectedRepo, ConnectedRepo.project_id == Project.id)
            .where(
                ConnectedRepo.workspace_id == project.workspace_id,
                ConnectedRepo.github_repo_id == repo.id,
                ConnectedRepo.project_id != project.id,
            )
        )
        repo_url = normalize_repo_url(repo.html_url)
        other = other or await self.session.scalar(
            select(Project.key).where(
                Project.workspace_id == project.workspace_id, Project.repo_url == repo_url, Project.id != project.id
            )
        )
        if other is not None:
            raise RepoTaken(f"{other} already uses {repo.full_name}")
        await self.session.execute(delete(ConnectedRepo).where(ConnectedRepo.project_id == project.id))
        self.session.add(ConnectedRepo(
            workspace_id=project.workspace_id, project_id=project.id, installation_ref=installation.id,
            github_repo_id=repo.id, full_name=repo.full_name, default_branch=repo.default_branch,
            private=repo.private, html_url=repo.html_url, connected_by_id=member.user_id, connected_at=_now(),
        ))
        project.repo_url = repo_url
        AuditLog(self.session).record(
            workspace_id=project.workspace_id, project_id=project.id, action="project.repo_connected",
            target=repo.full_name, actor_type=AuthorType.USER, actor_user_id=member.user_id,
            details={"github_repo_id": repo.id, "account": installation.account_login},
        )
        await self.session.commit()
        connected = await self.connected(access)
        assert connected is not None
        return connected

    async def disconnect(self, access: ProjectAccess) -> None:
        """Stop reaching the project's repo through the app. Its repo address stays, for the CLI."""
        project = access.project
        repo = await self.session.scalar(select(ConnectedRepo).where(ConnectedRepo.project_id == project.id))
        if repo is None:
            raise NotFound("This project has no connected repo")
        AuditLog(self.session).record(
            workspace_id=project.workspace_id, project_id=project.id, action="project.repo_disconnected",
            target=repo.full_name, actor_type=AuthorType.USER, actor_user_id=access.member.user_id,
        )
        await self.session.delete(repo)
        await self.session.commit()

    # -- lookups -----------------------------------------------------------------------

    async def _installations(self, workspace_id: uuid.UUID) -> list[GitHubInstallation]:
        return list(await self.session.scalars(
            select(GitHubInstallation)
            .where(GitHubInstallation.workspace_id == workspace_id)
            .order_by(GitHubInstallation.account_login)
        ))

    async def _installation_row(self, workspace_id: uuid.UUID, ref: uuid.UUID) -> GitHubInstallation:
        row = await self.session.scalar(
            select(GitHubInstallation).where(GitHubInstallation.workspace_id == workspace_id, GitHubInstallation.id == ref)
        )
        if row is None:
            raise NotFound("No such GitHub installation in this workspace")
        return row
