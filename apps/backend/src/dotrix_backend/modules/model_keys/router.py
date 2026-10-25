"""Personal model keys and workspace-scoped access checks."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from dotrix_backend.api.deps import (
    CurrentUser,
    SessionDep,
    SettingsDep,
    require_permission,
)
from dotrix_backend.core.crypto import Secrets
from dotrix_backend.core.openapi import errors
from dotrix_backend.modules.agents.llm import available_models
from dotrix_backend.modules.workspaces.models import Membership
from dotrix_backend.modules.workspaces.permissions import Permission

from .schemas import (
    DefaultCodingToolSave,
    DefaultModelSave,
    ModelAccessRead,
    ModelKeySave,
    PersonalModelsRead,
)
from .service import PersonalKeys, run_keys

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["models"], responses=errors(401, 403, 404))


def get_secrets(request: Request) -> Secrets:
    return request.app.state.secrets


SecretsDep = Annotated[Secrets, Depends(get_secrets)]


@router.get("/model-access")
async def model_access(
    member: Annotated[Membership, Depends(require_permission(Permission.VIEW))], session: SessionDep,
    settings: SettingsDep, secrets: SecretsDep,
) -> ModelAccessRead:
    """Whether your runs have a usable provider here. Only availability is shared, never keys."""
    keys = await run_keys(session, secrets, member.workspace_id, member.user_id)
    models = available_models(settings, connected=set(keys.keys))
    return ModelAccessRead(
        ready=bool(models), models=models, providers=list(dict.fromkeys(m.partition(":")[0] for m in models)),
        can_store_keys=secrets.configured,
    )


me_router = APIRouter(prefix="/me", tags=["models"], responses=errors(401))


@me_router.get("/models")
async def get_my_models(user: CurrentUser, session: SessionDep, settings: SettingsDep, secrets: SecretsDep) -> PersonalModelsRead:
    """Your own model keys (last four characters only) and your default model for new
    conversations. Your own key pays for your runs in every workspace."""
    return await PersonalKeys(session, secrets).read(user, settings)


@me_router.put("/models", responses=errors(422))
async def set_my_default_model(
    data: DefaultModelSave, user: CurrentUser, session: SessionDep, settings: SettingsDep, secrets: SecretsDep
) -> PersonalModelsRead:
    """Your default model for new conversations (null: each project's), using your own provider key."""
    return await PersonalKeys(session, secrets).set_default(user, data, settings)


@me_router.put("/coding-tool")
async def set_my_coding_tool(
    data: DefaultCodingToolSave, user: CurrentUser, session: SessionDep, settings: SettingsDep, secrets: SecretsDep,
) -> PersonalModelsRead:
    """Your default for new coding sessions; null chooses a tool with an available provider key."""
    user.default_coding_tool = data.default_coding_tool
    await session.commit()
    return await PersonalKeys(session, secrets).read(user, settings)


@me_router.put("/model-keys/{provider}", responses=errors(404, 422, 503))
async def save_my_model_key(
    provider: str, data: ModelKeySave, user: CurrentUser, session: SessionDep, settings: SettingsDep, secrets: SecretsDep
) -> PersonalModelsRead:
    """Connect or replace your own key for a supported model provider; stored
    encrypted, never shown again. 503 `encryption_not_configured` when the server can't store keys."""
    return await PersonalKeys(session, secrets).save(user, provider, data, settings)


@me_router.delete("/model-keys/{provider}", responses=errors(404))
async def remove_my_model_key(
    provider: str, user: CurrentUser, session: SessionDep, settings: SettingsDep, secrets: SecretsDep
) -> PersonalModelsRead:
    """Remove your own key; this provider becomes unavailable to your runs."""
    return await PersonalKeys(session, secrets).remove(user, provider, settings)
