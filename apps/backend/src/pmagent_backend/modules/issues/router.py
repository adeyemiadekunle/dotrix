"""Jira-style issues: create, update, log, board, backlog, epics, next, claim (FR-29, FR-30, FR-32).

Issue keys (`KUN-42`) go in the URL and are case-insensitive.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from pmagent_backend.api.deps import SessionDep, require_permission
from pmagent_backend.core.openapi import errors
from pmagent_backend.modules.projects.deps import (
    ProjectAccess,
    ProjectViewer,
    require_project_permission,
)
from pmagent_backend.modules.workspaces.models import Membership
from pmagent_backend.modules.workspaces.permissions import Permission

from .models import AgentAssignee, IssueStatus, IssueType
from .schemas import (
    Board,
    ClaimRequest,
    CommentCreate,
    EpicProgress,
    IssueCreate,
    IssueRead,
    IssueSummary,
    IssueUpdate,
    RankRequest,
    WorkspaceIssue,
)
from .service import IssueActor, IssueService

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/issues",
    tags=["issues"],
    responses=errors(401, 404),
)

Editor = Annotated[ProjectAccess, Depends(require_project_permission(Permission.EDIT_ISSUES))]

ASSIGNEE_FILTER = Query(
    default=None, description="A user ID, an agent (coding-agent, claude-code, codex), or `none`"
)


def _actor(access: ProjectAccess, agent: AgentAssignee | None = None) -> IssueActor:
    return IssueActor(access.member, agent)


@router.post("", status_code=status.HTTP_201_CREATED, responses=errors(403, 422))
async def create_issue(data: IssueCreate, access: Editor, session: SessionDep) -> IssueRead:
    """Create an issue. It gets the next key (`KUN-43`), never reused. Stories need acceptance
    criteria and bugs need repro steps in the description. Sub-tasks need a parent story, task,
    or bug; other types may sit under an epic. Assigning the built-in coding agent needs the
    instruct-coding-agent permission."""
    return await IssueService(session).create(access.project, _actor(access, data.as_agent), data)


@router.get("", responses=errors(422))
async def list_issues(
    access: ProjectViewer,
    session: SessionDep,
    type: Annotated[list[IssueType], Query()] = [],  # noqa: B006 (FastAPI query list)
    status: Annotated[list[IssueStatus], Query()] = [],  # noqa: B006
    assignee: str | None = ASSIGNEE_FILTER,
    label: str | None = None,
    parent: str | None = Query(default=None, description="Children of this issue key"),
    ready: bool = Query(default=False, description="Only issues that could start now"),
    order: Literal["rank", "priority", "created", "updated"] = "rank",
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> list[IssueSummary]:
    """Issues, filtered. `order=rank` is the backlog order; `priority` is urgent first, then
    earliest due, then oldest."""
    return await IssueService(session).list(
        access.project, types=type, statuses=status, assignee=assignee, label=label,
        parent=parent, ready=ready, order=order, limit=limit, offset=offset,
    )


@router.get("/board", responses=errors(422))
async def get_board(
    access: ProjectViewer,
    session: SessionDep,
    type: Annotated[list[IssueType], Query()] = [],  # noqa: B006
    assignee: str | None = ASSIGNEE_FILTER,
    label: str | None = None,
    epic: str | None = Query(default=None, description="Only this epic's issues"),
) -> Board:
    """Issues in one column per status, each in backlog order."""
    return await IssueService(session).board(
        access.project, types=type, assignee=assignee, label=label, epic=epic
    )


@router.get("/backlog", responses=errors(422))
async def get_backlog(
    access: ProjectViewer,
    session: SessionDep,
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> list[IssueSummary]:
    """Everything not done, in rank order (drag to reorder with `/rank`)."""
    open_statuses = [s for s in IssueStatus if s is not IssueStatus.DONE]
    return await IssueService(session).list(
        access.project, statuses=open_statuses, order="rank", limit=limit, offset=offset
    )


@router.get("/epics")
async def list_epics(access: ProjectViewer, session: SessionDep) -> list[EpicProgress]:
    """Each epic with how many of its children are done."""
    return await IssueService(session).epics(access.project)


@router.get("/next", responses=errors(422))
async def next_issue(
    access: ProjectViewer,
    session: SessionDep,
    as_agent: AgentAssignee | None = Query(default=None, description="Ask for this agent, e.g. claude-code"),
) -> IssueRead:
    """What to work on: your (or the agent's) in-progress issue first, so a crashed session
    resumes; otherwise the best ready issue. 404 `nothing_ready` when there's none."""
    return await IssueService(session).next(access.project, _actor(access, as_agent), as_agent)


@router.post("/claim", responses=errors(403, 409, 422))
async def claim_issue(data: ClaimRequest, access: Editor, session: SessionDep) -> IssueRead:
    """Atomically take a ready issue (a given key, or the next one) and start it: it's assigned
    to you or the agent and moves to `in_progress`. Two claimers never get the same issue."""
    return await IssueService(session).claim(access.project, _actor(access), data)


@router.get("/{key}")
async def get_issue(key: str, access: ProjectViewer, session: SessionDep) -> IssueRead:
    """An issue with its dependencies, children, watchers, and full log."""
    return await IssueService(session).get(access.project, key)


@router.patch("/{key}", responses=errors(403, 422))
async def update_issue(key: str, data: IssueUpdate, access: Editor, session: SessionDep) -> IssueRead:
    """Change fields; only what you send changes, and every change is logged (old → new).
    `depends_on` replaces the list and can't create a cycle. Only a person moves an issue to
    `done`; coding tools (`as_agent`) stop at `review`."""
    return await IssueService(session).update(access.project, key, _actor(access, data.as_agent), data)


@router.post("/{key}/comments", status_code=status.HTTP_201_CREATED, responses=errors(403, 422))
async def comment_on_issue(
    key: str, data: CommentCreate, access: Editor, session: SessionDep
) -> IssueRead:
    """Add a comment to the issue's log."""
    return await IssueService(session).comment(access.project, key, _actor(access, data.as_agent), data)


@router.post("/{key}/rank", responses=errors(403, 422))
async def rank_issue(key: str, data: RankRequest, access: Editor, session: SessionDep) -> IssueRead:
    """Move an issue in the backlog: just before or just after another issue."""
    return await IssueService(session).rank(access.project, key, data)


@router.put("/{key}/watch")
async def watch_issue(key: str, access: ProjectViewer, session: SessionDep) -> IssueRead:
    """Get notified about changes to this issue."""
    return await IssueService(session).watch(access.project, key, access.member.user_id, on=True)


@router.delete("/{key}/watch")
async def unwatch_issue(key: str, access: ProjectViewer, session: SessionDep) -> IssueRead:
    """Stop watching this issue."""
    return await IssueService(session).watch(access.project, key, access.member.user_id, on=False)


workspace_router = APIRouter(
    prefix="/workspaces/{workspace_id}/issues", tags=["issues"], responses=errors(401, 404)
)


@workspace_router.get("", responses=errors(422))
async def list_workspace_issues(
    member: Annotated[Membership, Depends(require_permission(Permission.VIEW))],
    session: SessionDep,
    type: Annotated[list[IssueType], Query()] = [],  # noqa: B006
    status: Annotated[list[IssueStatus], Query()] = [],  # noqa: B006
    assignee: str | None = Query(
        default=None, description="`me`, a user ID, an agent (coding-agent, claude-code, codex), or `none`"
    ),
    reporter: str | None = Query(default=None, description="`me` or a user ID"),
    watching: bool = Query(default=False, description="Only issues you watch"),
    label: str | None = None,
    due_before: date | None = Query(default=None, description="Due on or before this day"),
    order: Literal["due", "priority", "created", "updated"] = "due",
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> list[WorkspaceIssue]:
    """Issues across every project in the workspace that you can see (My issues, Tasks), each
    with its project. Restricted projects you aren't on are left out. `order=due` is earliest
    due first (no date last), then most urgent."""
    return await IssueService(session).across_projects(
        member, types=type, statuses=status, assignee=assignee, reporter=reporter, watching=watching,
        label=label, due_before=due_before, order=order, limit=limit, offset=offset,
    )
