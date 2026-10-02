"""Keeping each connected repo's checkout current, and finding it for an agent run."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core.errors import NotFound
from pmagent_backend.modules.auth.github import GitHubUnavailable
from pmagent_backend.modules.connectors.models import ConnectedRepo, GitHubInstallation

from .checkouts import CheckoutError, CodeCheckouts, RepoRef

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Checkout:
    """A checkout an agent run can read."""

    root: Path
    full_name: str
    default_branch: str
    sha: str


class CodeService:
    def __init__(self, session: AsyncSession, checkouts: CodeCheckouts) -> None:
        self.session = session
        self.checkouts = checkouts

    async def _connected(self, project_id: uuid.UUID) -> tuple[ConnectedRepo, GitHubInstallation] | None:
        found = (await self.session.execute(
            select(ConnectedRepo, GitHubInstallation)
            .join(GitHubInstallation, GitHubInstallation.id == ConnectedRepo.installation_ref)
            .where(ConnectedRepo.project_id == project_id)
        )).first()
        return (found[0], found[1]) if found else None

    async def sync(self, project_id: uuid.UUID) -> str | None:
        """Fetch the project's repo afresh and record how it went (the commit, or why not).
        Returns the commit, or None if it didn't work or the project has no connected repo."""
        found = await self._connected(project_id)
        if found is None:
            return None
        repo, installation = found
        ref = RepoRef(
            workspace_id=repo.workspace_id, project_id=repo.project_id, installation_id=installation.installation_id,
            full_name=repo.full_name, default_branch=repo.default_branch,
        )
        try:
            if installation.suspended_at is not None:
                raise CheckoutError(f"The GitHub App is suspended on {installation.account_login}")
            sha = await self.checkouts.sync(ref)
        except (CheckoutError, NotFound, GitHubUnavailable) as exc:
            # NotFound: the app can't reach the installation any more (the webhook will tidy up);
            # GitHubUnavailable: GitHub is down or refused the app a token.
            repo.checkout_error = str(exc)[:500]
            await self.session.commit()
            logger.warning("couldn't check out %s for project %s: %s", repo.full_name, project_id, exc)
            return None
        repo.checkout_sha, repo.checked_out_at, repo.checkout_error = sha, datetime.now(UTC), None
        await self.session.commit()
        return sha

    async def ensure(self, workspace_id: uuid.UUID, project_id: uuid.UUID) -> Checkout | None:
        """The project's checkout for an agent run: synced first if this machine has none, or if a
        push since made it stale. None without a connected repo or a checkout that works."""
        found = await self._connected(project_id)
        if found is None or found[0].workspace_id != workspace_id:
            return None
        repo = found[0]
        head = await self.checkouts.head(workspace_id, project_id)
        if head is None or (repo.last_push_sha and head != repo.last_push_sha):
            head = await self.sync(project_id) or head
        if head is None:
            return None
        return Checkout(self.checkouts.path(workspace_id, project_id), repo.full_name, repo.default_branch, head)

    async def prune(self) -> int:
        """Delete checkouts whose project is no longer connected (or was moved)."""
        keep = {(w, p) for w, p in await self.session.execute(select(ConnectedRepo.workspace_id, ConnectedRepo.project_id))}
        return await self.checkouts.prune(keep)
