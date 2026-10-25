"""An organisation's own model provider keys (Settings → Models)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from dotrix_backend.api.deps import (
    CurrentUser,
    SessionDep,
    SettingsDep,
    get_membership,
    require_permission,
)
from dotrix_backend.core.crypto import Secrets
from dotrix_backend.core.openapi import errors
from dotrix_backend.modules.agents.llm import available_models
from dotrix_backend.modules.workspaces.models import Membership
from dotrix_backend.modules.workspaces.permissions import Permission, can

from .schemas import (
    DefaultCodingToolSave,
    DefaultModelSave,
    ModelAccessRead,
    ModelKeyRead,
    ModelKeySave,
    PersonalModelsRead,
)
from .service import ModelKeys, PersonalKeys, personal_keys_allowed, run_keys

router = APIRouter(prefix="/workspaces/{workspace_id}/model-keys", tags=["models"], responses=errors(401, 403, 404))

Manager = Annotated[Membership, Depends(require_permission(Permission.MANAGE_WORKSPACE))]


def get_secrets(request: Request) -> Secrets:
    return request.app.state.secrets


SecretsDep = Annotated[Secrets, Depends(get_secrets)]


@router.get("/access")
async def model_access(
    member: Annotated[Membership, Depends(get_membership)], session: SessionDep,
    settings: SettingsDep, secrets: SecretsDep,
) -> ModelAccessRead:
    """Whether your runs have a usable provider here. Only availability is shared, never keys."""
    keys = await run_keys(session, secrets, member.workspace_id, member.user_id)
    models = available_models(settings, connected=set(keys.keys))
    return ModelAccessRead(
        ready=bool(models), models=models, providers=list(dict.fromkeys(m.partition(":")[0] for m in models)),
        personal_keys_allowed=await personal_keys_allowed(session, member.workspace_id),
        can_manage_keys=can(member, Permission.MANAGE_WORKSPACE), can_store_keys=secrets.configured,
    )


@router.get("")
async def list_model_keys(member: Manager, session: SessionDep, settings: SettingsDep, secrets: SecretsDep) -> list[ModelKeyRead]:
    """Each model provider: whether this workspace has its own key (its last four characters,
    never the key), whether the server's key stands in without one, the provider's models, and
    when it last refused a run for a rate limit or quota. Owners and admins."""
    return await ModelKeys(session, secrets).list(member.workspace_id, settings)


@router.put("/{provider}", responses=errors(422, 503))
async def save_model_key(
    provider: str, data: ModelKeySave, member: Manager, session: SessionDep, settings: SettingsDep, secrets: SecretsDep
) -> ModelKeyRead:
    """Connect or replace this workspace's key for a supported model provider. It's
    stored encrypted and used for every agent run here that picks one of the provider's models.
    503 `encryption_not_configured` when the server can't store keys. Owners and admins; audited."""
    return await ModelKeys(session, secrets).save(member, provider, data, settings)


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_model_key(provider: str, member: Manager, session: SessionDep, secrets: SecretsDep) -> None:
    """Remove this workspace's key for a provider; its models stop running here unless the server
    lends its own. Owners and admins; audited."""
    await ModelKeys(session, secrets).remove(member, provider)


me_router = APIRouter(prefix="/me", tags=["models"], responses=errors(401))


@me_router.get("/models")
async def get_my_models(user: CurrentUser, session: SessionDep, settings: SettingsDep, secrets: SecretsDep) -> PersonalModelsRead:
    """Your own model keys (last four characters only) and your default model for new
    conversations. Your keys run what you start: always in your personal workspace, and in an
    organisation that allows personal keys (otherwise its own key does)."""
    return await PersonalKeys(session, secrets).read(user, settings)


@me_router.put("/models", responses=errors(422))
async def set_my_default_model(
    data: DefaultModelSave, user: CurrentUser, session: SessionDep, settings: SettingsDep, secrets: SecretsDep
) -> PersonalModelsRead:
    """Your default model for new conversations (null: each project's). It's used where it can
    run: with your own key for its provider, or where the workspace lets people choose models."""
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
    """Remove your own key for a provider; what you start uses the workspace's key again."""
    return await PersonalKeys(session, secrets).remove(user, provider, settings)
