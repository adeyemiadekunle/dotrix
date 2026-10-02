"""Connecting GitHub: the app's installations in a workspace, and each project's repo."""
from __future__ import annotations

import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status

from pmagent_backend.api.deps import SessionDep, SettingsDep, require_permission
from pmagent_backend.core.errors import Unprocessable
from pmagent_backend.core.openapi import errors
from pmagent_backend.modules.auth.github import GitHubDep
from pmagent_backend.modules.projects.deps import ProjectManager, ProjectViewer
from pmagent_backend.modules.workspaces.models import Membership
from pmagent_backend.modules.workspaces.permissions import Permission

from . import webhook
from .github_app import GitHubAppDep
from .schemas import (
    ConnectedRepoRead,
    GitHubStatus,
    InstallationAdd,
    InstallationRead,
    RepoConnect,
    RepoOption,
)
from .service import ConnectorService

logger = logging.getLogger(__name__)

Manager = Annotated[Membership, Depends(require_permission(Permission.MANAGE_PROJECTS))]

workspace_router = APIRouter(prefix="/workspaces/{workspace_id}/github", tags=["github"], responses=errors(401, 403, 404))


@workspace_router.get("")
async def get_github_status(member: Manager, session: SessionDep, app: GitHubAppDep) -> GitHubStatus:
    """Whether the GitHub App is set up here, where to install it, and the GitHub accounts it's
    installed on that this workspace uses. Owners and admins."""
    return await ConnectorService(session, app).status(member)


@workspace_router.post("/installations", responses=errors(422, 503))
async def add_github_installation(
    data: InstallationAdd, member: Manager, session: SessionDep, app: GitHubAppDep, oauth: GitHubDep
) -> InstallationRead:
    """Add the app's installation on a GitHub account to this workspace: after installing it
    (GitHub's setup redirect gives `installation_id`), a GitHub sign-in's `code` proves you can
    manage it (403 if GitHub says you can't). Owners and admins."""
    return await ConnectorService(session, app).add_installation(member, data, oauth)


@workspace_router.delete(
    "/installations/{installation_ref}", status_code=status.HTTP_204_NO_CONTENT, responses=errors(503)
)
async def remove_github_installation(
    installation_ref: uuid.UUID, member: Manager, session: SessionDep, app: GitHubAppDep
) -> None:
    """Forget a GitHub account here; its projects' repos are disconnected. The app stays
    installed on GitHub until uninstalled there. Owners and admins."""
    await ConnectorService(session, app).remove_installation(member, installation_ref)


@workspace_router.get("/repos", responses=errors(503))
async def list_github_repos(member: Manager, session: SessionDep, app: GitHubAppDep) -> list[RepoOption]:
    """Every repo the workspace's installations can see, private ones included, and which
    project uses each. Owners and admins."""
    return await ConnectorService(session, app).repos(member)


project_router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/repository", tags=["github"], responses=errors(401, 404)
)


@project_router.get("")
async def get_project_repository(access: ProjectViewer, session: SessionDep, app: GitHubAppDep) -> ConnectedRepoRead | None:
    """The repo the project's code lives in, connected through the GitHub App (null if none)."""
    return await ConnectorService(session, app).connected(access)


@project_router.put("", responses=errors(403, 409, 422, 503))
async def connect_project_repository(
    data: RepoConnect, access: ProjectManager, session: SessionDep, app: GitHubAppDep
) -> ConnectedRepoRead:
    """Connect the project to a repo one of the workspace's installations can see (replacing
    any it had); its repo address follows. 409 if another project here uses it. Owners and admins."""
    return await ConnectorService(session, app).connect(access, data)


@project_router.delete("", status_code=status.HTTP_204_NO_CONTENT, responses=errors(403))
async def disconnect_project_repository(access: ProjectManager, session: SessionDep, app: GitHubAppDep) -> None:
    """Stop reaching the project's repo through the app (its address stays). Owners and admins."""
    await ConnectorService(session, app).disconnect(access)


webhook_router = APIRouter(prefix="/github", tags=["github"])


@webhook_router.post("/webhook", status_code=status.HTTP_202_ACCEPTED, responses=errors(401, 422, 503))
async def github_webhook(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    x_github_event: Annotated[str, Header()] = "",
    x_hub_signature_256: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    """GitHub's deliveries for the app (pushes, installs and uninstalls, repos added or
    removed), signed with the webhook secret. Not for people: GitHub calls it."""
    body = await request.body()
    webhook.verify_signature(settings, body, x_hub_signature_256)
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise Unprocessable("The delivery isn't JSON") from exc
    done = await webhook.handle(session, x_github_event, payload)
    logger.info("github webhook %s: %s", x_github_event, done)
    return {"result": done}
