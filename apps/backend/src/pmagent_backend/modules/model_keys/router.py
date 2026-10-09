"""An organisation's own model provider keys (Settings → Models)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from pmagent_backend.api.deps import SessionDep, SettingsDep, require_permission
from pmagent_backend.core.crypto import Secrets
from pmagent_backend.core.openapi import errors
from pmagent_backend.modules.workspaces.models import Membership
from pmagent_backend.modules.workspaces.permissions import Permission

from .schemas import ModelKeyRead, ModelKeySave
from .service import ModelKeys

router = APIRouter(prefix="/workspaces/{workspace_id}/model-keys", tags=["models"], responses=errors(401, 403, 404))

Manager = Annotated[Membership, Depends(require_permission(Permission.MANAGE_WORKSPACE))]


def get_secrets(request: Request) -> Secrets:
    return request.app.state.secrets


SecretsDep = Annotated[Secrets, Depends(get_secrets)]


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
    """Connect or replace this workspace's key for `anthropic`, `openai`, or `google_genai`. It's
    stored encrypted and used for every agent run here that picks one of the provider's models.
    503 `encryption_not_configured` when the server can't store keys. Owners and admins; audited."""
    return await ModelKeys(session, secrets).save(member, provider, data, settings)


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_model_key(provider: str, member: Manager, session: SessionDep, secrets: SecretsDep) -> None:
    """Remove this workspace's key for a provider; its models stop running here unless the server
    lends its own. Owners and admins; audited."""
    await ModelKeys(session, secrets).remove(member, provider)
