"""Talk to the Project Manager agent; approve or reject its writes (FR-19, FR-35, FR-36)."""
from __future__ import annotations

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse

from pmagent_backend.api.deps import SessionDep, SettingsDep, require_permission
from pmagent_backend.core.openapi import errors
from pmagent_backend.modules.projects.deps import ProjectAccess, require_project_permission
from pmagent_backend.modules.workspaces.models import Membership
from pmagent_backend.modules.workspaces.permissions import Permission

from .llm import available_models
from .models import RunKind
from .runner import AgentRunner
from .schemas import (
    AgentRunRead,
    ApprovalRead,
    ArchitectureDraftRequest,
    DecisionsRequest,
    ModelOption,
    OutputItemUpdate,
    RunCreate,
    ThreadRead,
    ThreadRename,
    TriageRequest,
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
SetupManager = Annotated[ProjectAccess, Depends(require_project_permission(Permission.MANAGE_PROJECTS))]
IssueEditor = Annotated[ProjectAccess, Depends(require_project_permission(Permission.EDIT_ISSUES))]


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED, responses=errors(403, 409, 422, 503))
async def create_run(data: RunCreate, access: Chatter, agents: Agents, settings: SettingsDep) -> AgentRunRead:
    """Send a message to the project's agents: `agent` picks who answers (`auto`, the Project
    Manager with the specialists it needs, or one specialist, who leads and may ask the others).
    It runs in the background: poll the run until `status` is `completed`, `failed`, or
    `awaiting_approval`. Agents stay in Chat Mode unless you instruct a change, and every write
    pauses for approval. Pass `thread_id` to continue a conversation; a new one may pick its
    `model` (fixed from then on: 409 `model_locked` for another on an existing conversation;
    403 without agents:choose_model; 422 `model_not_available`). 503 `model_unavailable` if the
    model has no API key."""
    available = available_models(settings, access.project.model)
    return await agents.create_run(access, data, available=available)


@router.post("/briefing", status_code=status.HTTP_202_ACCEPTED, responses=errors(503))
async def create_briefing(access: Chatter, agents: Agents) -> AgentRunRead:
    """Ask for the daily briefing. Read-only: any write it attempts is rejected automatically."""
    return await agents.briefing(access)


@router.post("/triage", status_code=status.HTTP_202_ACCEPTED, responses=errors(422, 503))
async def triage_report(data: TriageRequest, access: Chatter, agents: Agents) -> AgentRunRead:
    """Have the Project Manager triage a bug report or feature request: it looks for duplicates on
    the board and in the documents, then proposes a comment on the existing issue or a new issue
    with its type, priority, and links (each waits for approval). A new conversation."""
    return await agents.triage(access, data)


@router.post("/issues/{key}/review", status_code=status.HTTP_202_ACCEPTED, responses=errors(503))
async def review_issue(key: str, access: Chatter, agents: Agents) -> AgentRunRead:
    """Have the Reviewer review one issue against its acceptance criteria. It recommends closing
    it or sending it back, and records each unmet criterion as a finding in the run's
    `outputs`. A new conversation; 404 for an unknown key."""
    return await agents.review_issue(access, key)


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
    kind: RunKind | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[AgentRunRead]:
    """Recent runs, newest first; filter by `thread_id` to read one conversation, or by `kind`
    (e.g. `briefing` for past daily briefings)."""
    return await agents.list(access, thread_id=thread_id, kind=kind, limit=limit)


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


@router.post("/runs/{run_id}/decisions", responses=errors(403, 409, 422))
async def decide_approvals(
    run_id: uuid.UUID, data: DecisionsRequest, access: Chatter, agents: Agents
) -> AgentRunRead:
    """Decide every pending action of a paused run (one decision each), then the run resumes.
    Changes are approved or rejected, with the reason sent back to the agent; they need the
    approve permission, and changes to `architecture/` an owner or admin (403 otherwise, and
    the run keeps waiting). A checkpoint (`checkpoint`, the agent's plan before a large job)
    is answered by whoever asked, or anyone who may approve: approve to continue, `steer` with
    the changes as `reason`, or reject to stop. Your decision is recorded next to who
    instructed the run."""
    return await agents.decide(access, run_id, data)


models_router = APIRouter(prefix="/workspaces/{workspace_id}/models", tags=["agents"], responses=errors(401, 404))


@models_router.get("")
async def list_models(
    member: Annotated[Membership, Depends(require_permission(Permission.VIEW))], settings: SettingsDep
) -> list[ModelOption]:
    """The models a conversation can be started on here: those whose provider has an API key.
    A project's own model is always allowed too, even if it isn't listed."""
    return [
        ModelOption(id=model, provider=model.partition(":")[0], name=model.partition(":")[2])
        for model in available_models(settings)
    ]


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
    return await agents.workspace_pending(member)


@router.patch("/runs/{run_id}/outputs/{output_id}/items/{index}", responses=errors(422))
async def update_run_output_item(
    run_id: uuid.UUID, output_id: uuid.UUID, index: int, data: OutputItemUpdate, access: IssueEditor, agents: Agents
) -> AgentRunRead:
    """Act on one item of a run's result: `done` with what it became (e.g. the issue key you
    created from a finding), `dismissed` with why, or `open` again. Anyone who works the board."""
    return await agents.update_output_item(access, run_id, output_id, index, data)
