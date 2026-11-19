"""Whether a workspace can be used on this server.

Personal workspaces always can. Organisations only while `DOTRIX_ORGANISATIONS` allows them
(`Settings.organisations_enabled`: off on a deployed server unless turned on), so personal
workspaces can launch first. A hidden organisation keeps its data; its members get 404, as
non-members do, and it isn't listed.
"""
from __future__ import annotations

from dotrix_backend.core.errors import Forbidden
from dotrix_backend.core.settings import Settings

from .models import Workspace, WorkspaceKind


class OrganisationsUnavailable(Forbidden):
    code = "organisations_unavailable"

    def __init__(self) -> None:
        super().__init__(
            "Organisation workspaces aren't available yet. "
            "Your personal workspace has everything you need to work on your own."
        )


def available(workspace: Workspace, settings: Settings) -> bool:
    return workspace.kind is WorkspaceKind.PERSONAL or settings.organisations_enabled


def require_organisations(settings: Settings) -> None:
    if not settings.organisations_enabled:
        raise OrganisationsUnavailable()
