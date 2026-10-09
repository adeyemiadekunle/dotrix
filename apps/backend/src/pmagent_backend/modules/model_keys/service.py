"""An organisation's own model provider keys: connect, replace, remove; the keys a run uses; and
when a provider last refused a run for its rate limit or quota."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core.crypto import Secrets
from pmagent_backend.core.errors import NotFound, Unprocessable
from pmagent_backend.core.settings import Settings
from pmagent_backend.modules.agents.llm import PROVIDERS, server_key
from pmagent_backend.modules.audit.service import AuditLog
from pmagent_backend.modules.auth.models import User
from pmagent_backend.modules.knowledge.models import AuthorType
from pmagent_backend.modules.workspaces.models import Membership, Workspace, WorkspaceKind

from .models import UserModelKey, WorkspaceModelKey
from .schemas import DefaultModelSave, ModelKeyRead, ModelKeySave, PersonalModelsRead


def _now() -> datetime:
    return datetime.now(UTC)


def _provider(name: str) -> str:
    if name not in PROVIDERS:
        raise NotFound(f"No provider {name!r}; use one of: {', '.join(PROVIDERS)}")
    return name


class ModelKeys:
    def __init__(self, session: AsyncSession, secrets: Secrets) -> None:
        self.session = session
        self.secrets = secrets

    async def _rows(self, workspace_id: uuid.UUID) -> dict[str, WorkspaceModelKey]:
        rows = await self.session.scalars(select(WorkspaceModelKey).where(WorkspaceModelKey.workspace_id == workspace_id))
        return {row.provider: row for row in rows}

    # -- for runs ---------------------------------------------------------------------------

    async def keys(self, workspace_id: uuid.UUID) -> dict[str, str]:
        """provider -> the workspace's own key, decrypted (a key no configured secret can read
        is left out, so the run says the key is missing rather than failing obscurely)."""
        out: dict[str, str] = {}
        for provider, row in (await self._rows(workspace_id)).items():
            plain = self.secrets.decrypt(row.encrypted) if self.secrets.configured else None
            if plain:
                out[provider] = plain
        return out

    async def connected(self, workspace_id: uuid.UUID) -> set[str]:
        return set(await self._rows(workspace_id))

    async def limit_reached(self, workspace_id: uuid.UUID, provider: str, message: str) -> None:
        row = (await self._rows(workspace_id)).get(provider)
        if row is not None:
            row.limit_reached_at, row.limit_message = _now(), message[:500]
            await self.session.commit()

    async def limit_cleared(self, workspace_id: uuid.UUID, provider: str) -> None:
        row = (await self._rows(workspace_id)).get(provider)
        if row is not None and row.limit_reached_at is not None:
            row.limit_reached_at = row.limit_message = None
            await self.session.commit()

    # -- Settings → Models -------------------------------------------------------------------

    async def list(self, workspace_id: uuid.UUID, settings: Settings) -> list[ModelKeyRead]:
        rows = await self._rows(workspace_id)
        return [self._read(name, rows.get(name), settings) for name in PROVIDERS]

    async def save(self, member: Membership, provider: str, data: ModelKeySave, settings: Settings) -> ModelKeyRead:
        provider = _provider(provider)
        token = self.secrets.encrypt(data.api_key)  # 503 when the server can't store keys
        row = (await self._rows(member.workspace_id)).get(provider)
        if row is None:
            row = WorkspaceModelKey(workspace_id=member.workspace_id, provider=provider, encrypted=token,
                                    last4=data.api_key[-4:], added_by_id=member.user_id)
            self.session.add(row)
        else:
            row.encrypted, row.last4, row.added_by_id, row.updated_at = token, data.api_key[-4:], member.user_id, _now()
            row.limit_reached_at = row.limit_message = None
        self._audit(member, "model_key.saved", provider, {"last4": data.api_key[-4:]})
        await self.session.commit()
        await self.session.refresh(row)
        return self._read(provider, row, settings)

    async def remove(self, member: Membership, provider: str) -> None:
        provider = _provider(provider)
        row = (await self._rows(member.workspace_id)).get(provider)
        if row is None:
            raise NotFound(f"This workspace has no {PROVIDERS[provider].label} key")
        self._audit(member, "model_key.removed", provider, {"last4": row.last4})
        await self.session.delete(row)
        await self.session.commit()

    def _read(self, provider: str, row: WorkspaceModelKey | None, settings: Settings) -> ModelKeyRead:
        return ModelKeyRead(
            provider=provider, label=PROVIDERS[provider].label, connected=row is not None,
            last4=row.last4 if row else None, added_by_id=row.added_by_id if row else None,
            updated_at=row.updated_at if row else None,
            server_key=settings.server_model_keys and server_key(settings, provider) is not None,
            limit_reached_at=row.limit_reached_at if row else None,
            limit_message=row.limit_message if row else None,
            models=[m for m in dict.fromkeys([*settings.models, settings.default_model]) if m.startswith(f"{provider}:")],
        )

    def _audit(self, member: Membership, action: str, provider: str, details: dict) -> None:
        AuditLog(self.session).record(
            workspace_id=member.workspace_id, action=action, target=PROVIDERS[provider].label,
            actor_type=AuthorType.USER, actor_user_id=member.user_id, details={"provider": provider, **details},
        )



def _catalogue(settings: Settings) -> list[str]:
    return list(dict.fromkeys([*settings.models, settings.default_model]))


@dataclass
class RunKeys:
    """The keys a run uses: the workspace's, with the person's own over them where allowed."""

    keys: dict[str, str]
    personal: set[str]  # providers whose key is the person's own


async def personal_keys_allowed(session: AsyncSession, workspace_id: uuid.UUID) -> bool:
    workspace = await session.get(Workspace, workspace_id)
    return workspace is not None and (workspace.kind is WorkspaceKind.PERSONAL or workspace.personal_keys)


async def run_keys(
    session: AsyncSession, secrets: Secrets, workspace_id: uuid.UUID, user_id: uuid.UUID | None, *, own: bool = True
) -> RunKeys:
    """Order: the person's own key (when `own`, and the workspace allows personal keys) → the
    workspace's → the server's (llm.key_for). Automations pass `own=False`: they run on the
    workspace's key."""
    keys = await ModelKeys(session, secrets).keys(workspace_id)
    personal: dict[str, str] = {}
    if own and user_id is not None and await personal_keys_allowed(session, workspace_id):
        personal = await PersonalKeys(session, secrets).keys(user_id)
    return RunKeys(keys | personal, set(personal))


def may_choose(member: Membership, model: str, personal: set[str]) -> bool:
    """Picking a model other than the project's: people the workspace lets choose, or anyone
    whose own key pays for it."""
    from pmagent_backend.modules.workspaces.permissions import Permission, can

    return can(member, Permission.CHOOSE_MODEL) or model.partition(":")[0] in personal


class PersonalKeys:
    """A person's own keys and default model (Account → Models)."""

    def __init__(self, session: AsyncSession, secrets: Secrets) -> None:
        self.session = session
        self.secrets = secrets

    async def _rows(self, user_id: uuid.UUID) -> dict[str, UserModelKey]:
        rows = await self.session.scalars(select(UserModelKey).where(UserModelKey.user_id == user_id))
        return {row.provider: row for row in rows}

    async def keys(self, user_id: uuid.UUID) -> dict[str, str]:
        out: dict[str, str] = {}
        for provider, row in (await self._rows(user_id)).items():
            plain = self.secrets.decrypt(row.encrypted) if self.secrets.configured else None
            if plain:
                out[provider] = plain
        return out

    async def connected(self, user_id: uuid.UUID) -> set[str]:
        return set(await self._rows(user_id))

    async def read(self, user: User, settings: Settings) -> PersonalModelsRead:
        rows = await self._rows(user.id)
        return PersonalModelsRead(
            keys=[self._read(name, rows.get(name), settings) for name in PROVIDERS],
            default_model=user.default_model,
            models=_catalogue(settings),
        )

    async def save(self, user: User, provider: str, data: ModelKeySave, settings: Settings) -> PersonalModelsRead:
        provider = _provider(provider)
        token = self.secrets.encrypt(data.api_key)
        row = (await self._rows(user.id)).get(provider)
        if row is None:
            self.session.add(UserModelKey(user_id=user.id, provider=provider, encrypted=token, last4=data.api_key[-4:]))
        else:
            row.encrypted, row.last4, row.updated_at = token, data.api_key[-4:], _now()
            row.limit_reached_at = row.limit_message = None
        await self.session.commit()
        return await self.read(user, settings)

    async def remove(self, user: User, provider: str, settings: Settings) -> PersonalModelsRead:
        provider = _provider(provider)
        row = (await self._rows(user.id)).get(provider)
        if row is None:
            raise NotFound(f"You have no {PROVIDERS[provider].label} key")
        await self.session.delete(row)
        await self.session.commit()
        return await self.read(user, settings)

    async def set_default(self, user: User, data: DefaultModelSave, settings: Settings) -> PersonalModelsRead:
        if data.default_model is not None and data.default_model not in _catalogue(settings):
            raise Unprocessable(f"{data.default_model} isn't a model here; choose one of: {', '.join(_catalogue(settings))}")
        user.default_model = data.default_model
        await self.session.commit()
        return await self.read(user, settings)

    async def limit_reached(self, user_id: uuid.UUID, provider: str, message: str) -> None:
        row = (await self._rows(user_id)).get(provider)
        if row is not None:
            row.limit_reached_at, row.limit_message = _now(), message[:500]
            await self.session.commit()

    async def limit_cleared(self, user_id: uuid.UUID, provider: str) -> None:
        row = (await self._rows(user_id)).get(provider)
        if row is not None and row.limit_reached_at is not None:
            row.limit_reached_at = row.limit_message = None
            await self.session.commit()

    def _read(self, provider: str, row: UserModelKey | None, settings: Settings) -> ModelKeyRead:
        return ModelKeyRead(
            provider=provider, label=PROVIDERS[provider].label, connected=row is not None,
            last4=row.last4 if row else None, added_by_id=row.user_id if row else None,
            updated_at=row.updated_at if row else None, server_key=False,
            limit_reached_at=row.limit_reached_at if row else None,
            limit_message=row.limit_message if row else None,
            models=[m for m in _catalogue(settings) if m.startswith(f"{provider}:")],
        )
