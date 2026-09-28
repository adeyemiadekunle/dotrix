"""Talk to the Project Manager agent; approve or reject its writes (FR-19, FR-35, FR-36)."""
from __future__ import annotations

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse

from pmagent_backend.api.deps import SessionDep, require_permission
from pmagent_backend.core.openapi import errors
from pmagent_backend.modules.projects.deps import ProjectAccess, require_project_permission
from pmagent_backend.modules.workspaces.models import Membership
from pmagent_backend.modules.workspaces.permissions import Permission

from .runner import AgentRunner
from .schemas import (
    AgentRunRead,
    ApprovalRead,
    ArchitectureDraftRequest,
    DecisionsRequest,
    RunCreate,
    ThreadRead,
    ThreadRename,
    WorkspaceApprovalRead,
)
from .service import AgentService

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/agent",
    tags=["agents"],
    responses=errors(401, 403, 404),
)


def get_runner(request: Request) -> AgentRunner:
    return request.app.state.runner


def get_agent_service(
    session: SessionDep, runner: Annotated[AgentRunner, Depends(get_runner)]
) -> AgentService:
    return AgentService(session, runner)


Agents = Annotated[AgentService, Depends(get_agent_service)]
Chatter = Annotated[ProjectAccess, Depends(require_project_permission(Permission.CHAT))]
Approver = Annotated[ProjectAccess, Depends(require_project_permission(Permission.APPROVE_ACTIONS))]
SetupManager = Annotated[ProjectAccess, Depends(require_project_permission(Permission.MANAGE_PROJECTS))]


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED, responses=errors(409, 422, 503))
async def create_run(data: RunCreate, access: Chatter, agents: Agents) -> AgentRunRead:
    """Send a message to the Project Manager. It runs in the background: poll the run until
    `status` is `completed`, `failed`, or `awaiting_approval`. Agents stay in Chat Mode
    unless you instruct a change, and every write pauses for approval. Pass `thread_id` to
    continue a conversation. 503 `model_unavailable` if the project's model has no API key."""
    return await agents.create_run(access, data)


@router.post("/briefing", status_code=status.HTTP_202_ACCEPTED, responses=errors(503))
async def create_briefing(access: Chatter, agents: Agents) -> AgentRunRead:
    """Ask for the daily briefing. Read-only: any write it attempts is rejected automatically."""
    return await agents.briefing(access)


@router.post("/architecture-draft", status_code=status.HTTP_202_ACCEPTED, responses=errors(422, 503))
async def create_architecture_draft(
    data: ArchitectureDraftRequest, access: SetupManager, agents: Agents
) -> AgentRunRead:
    """Project setup (owners and admins): have the Architecture agent draft or update
    `architecture/overview.md` from the project's docs and an optional repo summary. It's never
    triggered by connecting a repo, and the write waits for an owner's or admin's approval."""
    return await agents.architecture_draft(access, data)


@router.get("/runs", responses=errors(422))
async def list_runs(
    access: Chatter,
    agents: Agents,
    thread_id: uuid.UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[AgentRunRead]:
    """Recent runs, newest first; filter by `thread_id` to read one conversation."""
    return await agents.list(access, thread_id=thread_id, limit=limit)


@router.get("/runs/{run_id}")
async def get_run(run_id: uuid.UUID, access: Chatter, agents: Agents) -> AgentRunRead:
    """A run's status, the PM's reply when done, and its approvals."""
    return await agents.get(access, run_id)


@router.post("/runs/{run_id}/stop", responses=errors(409))
async def stop_run(run_id: uuid.UUID, access: Chatter, agents: Agents) -> AgentRunRead:
    """Stop a run that's still working (queued or running). Whoever asked can stop it, and so
    can owners and admins. Changes already approved stay; the conversation can continue. A run
    waiting for approval isn't stopped: reject its actions instead."""
    return await agents.stop(access, run_id)


@router.get(
    "/runs/{run_id}/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "Server-sent events"}},
)
async def stream_run(run_id: uuid.UUID, access: Chatter, agents: Agents) -> StreamingResponse:
    """The Project Manager's reply as it's written, as server-sent events: `text` (everything so
    far, first), then `delta` (each new piece), then `end`. `activity` says what the PM is doing
    meanwhile ("Reading roadmap.md"); each replaces the last. If the run isn't working right
    now it's just `end`: read the run for its saved reply. `ping` events keep the connection open."""
    await agents.check_run(access, run_id)

    async def events():
        async for event, data in agents.runner.streams.follow(run_id):
            if event == "ping":
                yield ": ping\n\n"
                continue
            yield f"event: {event}\ndata: {json.dumps({'text': data})}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.patch("/threads/{thread_id}", responses=errors(422))
async def rename_thread(thread_id: uuid.UUID, data: ThreadRename, access: Chatter, agents: Agents) -> ThreadRead:
    """Rename a conversation."""
    return await agents.rename_thread(access, thread_id, data)


@router.get("/approvals")
async def list_pending_approvals(access: Chatter, agents: Agents) -> list[ApprovalRead]:
    """Every action waiting for a decision in this project: the tool, what it changes, and a
    diff for file writes."""
    return await agents.pending_approvals(access)


@router.post("/runs/{run_id}/decisions", responses=errors(409, 422))
async def decide_approvals(
    run_id: uuid.UUID, data: DecisionsRequest, access: Approver, agents: Agents
) -> AgentRunRead:
    """Approve or reject every pending action of a paused run (one decision each), then the
    run resumes. Rejection reasons are sent back to the agent. Needs the approve
    permission; changes to `architecture/` need an owner or admin (403 otherwise, and the
    run keeps waiting). Your decision is recorded next to who instructed the run."""
    return await agents.decide(access, run_id, data)


workspace_router = APIRouter(
    prefix="/workspaces/{workspace_id}/approvals", tags=["agents"], responses=errors(401, 403, 404)
)


@workspace_router.get("")
async def list_workspace_approvals(
    member: Annotated[Membership, Depends(require_permission(Permission.CHAT))], agents: Agents
) -> list[WorkspaceApprovalRead]:
    """Every agent action waiting for a decision across the workspace's projects, oldest first,
    with the project and the instruction it came from. Decide them per run with
    `POST .../agent/runs/{run_id}/decisions`."""
    return await agents.workspace_pending(member.workspace_id)
