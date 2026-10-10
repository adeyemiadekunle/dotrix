"""Jira-style issues: create, update, log, board, backlog, epics, next, claim (FR-29, FR-30, FR-32).

Issue keys (`KUN-42`) go in the URL and are case-insensitive.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status

from dotrix_backend.api.deps import SessionDep, SettingsDep, require_permission
from dotrix_backend.core.errors import NotFound
from dotrix_backend.core.openapi import errors
from dotrix_backend.core.storage import BlobStorage, get_storage, optional_storage
from dotrix_backend.modules.coding.router import Coding
from dotrix_backend.modules.coding.service import CODING_AGENTS
from dotrix_backend.modules.projects.deps import (
    ProjectAccess,
    ProjectViewer,
    require_project_permission,
)
from dotrix_backend.modules.projects.repository import ProjectRepository
from dotrix_backend.modules.workspaces.models import Membership
from dotrix_backend.modules.workspaces.permissions import Permission

from .models import AgentAssignee, IssueStatus, IssueType
from .schemas import (
    Board,
    ClaimRequest,
    CommentCreate,
    CommentUpdate,
    Emoji,
    EpicProgress,
    IssueCreate,
    IssueMove,
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

ARCHIVED_FILTER = Query(
    default="exclude", description="`exclude` archived issues (the default), `include` them, or `only` them"
)
logger = logging.getLogger(__name__)



OptionalStorage = Annotated[BlobStorage | None, Depends(optional_storage)]

ASSIGNEE_FILTER = Query(
    default=None, description="A user ID, an agent (coding-agent, claude-code, codex), or `none`"
)


def _actor(access: ProjectAccess, agent: AgentAssignee | None = None) -> IssueActor:
    return IssueActor(access.member, agent)


@router.post("", status_code=status.HTTP_201_CREATED, responses=errors(403, 422))
async def create_issue(data: IssueCreate, access: Editor, session: SessionDep, coding: Coding) -> IssueRead:
    """Create an issue. It gets the next key (`KUN-43`), never reused. Stories need acceptance
    criteria and bugs need repro steps in the description. Sub-tasks need a parent story, task,
    or bug; other types may sit under an epic. Assigning the built-in coding agent needs the
    instruct-coding-agent permission. Assigning a coding tool (`coding-agent`, `claude-code`,
    `codex`) also starts a coding session, waiting for approval, where coding is set up."""
    issue = await IssueService(session).create(access.project, _actor(access, data.as_agent), data)
    if data.as_agent is None and data.assignee_agent in CODING_AGENTS:
        await coding.start_for_assignment(access, issue.key)
    return issue


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
    archived: Literal["exclude", "include", "only"] = ARCHIVED_FILTER,
) -> list[IssueSummary]:
    """Issues, filtered. `order=rank` is the backlog order; `priority` is urgent first, then
    earliest due, then oldest."""
    return await IssueService(session).list(
        access.project, types=type, statuses=status, assignee=assignee, label=label,
        parent=parent, ready=ready, order=order, limit=limit, offset=offset, archived=archived,
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
async def update_issue(key: str, data: IssueUpdate, access: Editor, session: SessionDep, coding: Coding) -> IssueRead:
    """Change fields; only what you send changes, and every change is logged (old → new).
    `depends_on` replaces the list and can't create a cycle. Only a person moves an issue to
    `done`; coding tools (`as_agent`) stop at `review`. Assigning it to a coding tool starts a
    coding session, waiting for approval, where coding is set up."""
    issues = IssueService(session)
    to_coding = data.as_agent is None and data.assignee_agent in CODING_AGENTS
    before = (await issues.get(access.project, key)).assignee_agent if to_coding else None
    issue = await issues.update(access.project, key, _actor(access, data.as_agent), data)
    if to_coding and before != data.assignee_agent:
        await coding.start_for_assignment(access, issue.key)
    return issue


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


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT, responses=errors(403, 409))
async def delete_issue(key: str, access: Editor, session: SessionDep, storage: OptionalStorage) -> None:
    """Delete an issue with its log and files. It can't be undone (archive it to keep it). Owners
    and admins, or whoever reported it; 409 while it has sub-issues."""
    keys = await IssueService(session).delete(access.project, key, _actor(access))
    for stored in keys if storage is not None else []:  # after the commit: a failure only orphans a file
        try:
            await storage.delete(stored)
        except Exception:  # noqa: BLE001 - the issue is gone either way
            logger.warning("couldn't delete %s from storage", stored)


@router.post("/{key}/move", responses=errors(403, 409, 422))
async def move_issue(key: str, data: IssueMove, access: Editor, session: SessionDep) -> IssueRead:
    """Move an issue to another project in the workspace: it's created there with that project's
    next key, taking its log, comments, watchers, stars, and files, and deleted here. Its parent and
    dependencies stay behind (they belong to this project). 409 while it has sub-issues or coding
    sessions."""
    target = await ProjectRepository(session).visible(access.member, data.project_id)
    if target is None:
        raise NotFound("Project not found")
    return await IssueService(session).move(access.project, key, _actor(access), target)


@router.patch("/{key}/comments/{comment_id}", responses=errors(403, 422))
async def edit_issue_comment(
    key: str, comment_id: uuid.UUID, data: CommentUpdate, access: Editor, session: SessionDep
) -> IssueRead:
    """Change a comment's text (its author only); it's marked edited."""
    return await IssueService(session).edit_comment(access.project, key, _actor(access), comment_id, data.body)


@router.delete("/{key}/comments/{comment_id}", responses=errors(403))
async def delete_issue_comment(key: str, comment_id: uuid.UUID, access: Editor, session: SessionDep) -> IssueRead:
    """Delete a comment: its author, or owners and admins."""
    return await IssueService(session).delete_comment(access.project, key, _actor(access), comment_id)


@router.put("/{key}/comments/{comment_id}/reactions/{emoji}", responses=errors(422))
async def react_to_issue_comment(
    key: str, comment_id: uuid.UUID, emoji: Emoji, access: ProjectViewer, session: SessionDep
) -> IssueRead:
    """React to a comment with an emoji (once per emoji each)."""
    return await IssueService(session).react(access.project, key, access.member.user_id, comment_id, emoji, on=True)


@router.delete("/{key}/comments/{comment_id}/reactions/{emoji}")
async def unreact_to_issue_comment(
    key: str, comment_id: uuid.UUID, emoji: Emoji, access: ProjectViewer, session: SessionDep
) -> IssueRead:
    """Take back your reaction to a comment."""
    return await IssueService(session).react(access.project, key, access.member.user_id, comment_id, emoji, on=False)


@router.put("/{key}/star", status_code=status.HTTP_204_NO_CONTENT)
async def star_issue(key: str, access: ProjectViewer, session: SessionDep) -> None:
    """Star an issue for yourself (your Favorites; nobody else sees your stars)."""
    await IssueService(session).star(access.project, key, access.member.user_id, on=True)


@router.delete("/{key}/star", status_code=status.HTTP_204_NO_CONTENT)
async def unstar_issue(key: str, access: ProjectViewer, session: SessionDep) -> None:
    """Take your star off an issue (no error if it had none)."""
    await IssueService(session).star(access.project, key, access.member.user_id, on=False)


Storage = Annotated[BlobStorage, Depends(get_storage)]


@router.post("/{key}/attachments", status_code=status.HTTP_201_CREATED, responses=errors(403, 422, 503))
async def attach_file_to_issue(
    key: str,
    access: Editor,
    session: SessionDep,
    storage: Storage,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="Any file: an image, a PDF, a log, a design")],
) -> IssueRead:
    """Add a file to the issue, listed under it (any type; it isn't converted for the agents,
    unlike a project document). Anyone who may edit issues."""
    limit = settings.max_upload_mb * 1_000_000
    data = await file.read(limit + 1)  # one byte past the limit to notice an oversized file
    return await IssueService(session).attach(
        access.project, key, _actor(access), storage, file.filename or "file", data, max_bytes=limit
    )


@router.get(
    "/{key}/attachments/{attachment_id}",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}, "description": "The file"}} | errors(503),
)
async def download_issue_attachment(
    key: str, attachment_id: uuid.UUID, access: ProjectViewer, session: SessionDep, storage: Storage
) -> Response:
    """Download a file added to the issue, exactly as it was uploaded."""
    found = await IssueService(session).attachment(access.project, key, attachment_id)
    return Response(
        content=await storage.get(found.storage_key),
        media_type=found.content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(found.filename)}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{key}/attachments/{attachment_id}", responses=errors(403, 503))
async def remove_issue_attachment(
    key: str, attachment_id: uuid.UUID, access: Editor, session: SessionDep, storage: Storage
) -> IssueRead:
    """Take a file off the issue; the file is deleted."""
    return await IssueService(session).detach(access.project, key, _actor(access), storage, attachment_id)


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
    starred: bool = Query(default=False, description="Only issues you starred (your Favorites)"),
    archived: Literal["exclude", "include", "only"] = ARCHIVED_FILTER,
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
        member, types=type, statuses=status, assignee=assignee, reporter=reporter, watching=watching, starred=starred, archived=archived,
        label=label, due_before=due_before, order=order, limit=limit, offset=offset,
    )
