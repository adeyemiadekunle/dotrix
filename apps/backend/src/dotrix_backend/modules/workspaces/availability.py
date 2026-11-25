"""Whether a workspace can be used on this server.

Personal workspaces always can. Team workspaces only while `DOTRIX_TEAMS` allows them
(`Settings.teams_enabled`: off on a deployed server unless turned on), so personal
workspaces can launch first. A hidden team workspace keeps its data; its members get 404, as
non-members do, and it isn't listed.
"""
from __future__ import annotations

from dotrix_backend.core.errors import Forbidden
from dotrix_backend.core.settings import Settings

from .models import Workspace, WorkspaceKind


class TeamsUnavailable(Forbidden):
    code = "teams_unavailable"

    def __init__(self) -> None:
        super().__init__(
            "Team workspaces aren't available yet. "
            "Your personal workspace has everything you need to work on your own."
        )


def available(workspace: Workspace, settings: Settings) -> bool:
    return workspace.kind is WorkspaceKind.PERSONAL or settings.teams_enabled


def require_teams(settings: Settings) -> None:
    if not settings.teams_enabled:
        raise TeamsUnavailable()
