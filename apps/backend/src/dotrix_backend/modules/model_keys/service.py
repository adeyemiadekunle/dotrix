"""Personal provider keys, encrypted at rest; every run uses its requester's credentials."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.crypto import Secrets
from dotrix_backend.core.errors import NotFound, Unprocessable
from dotrix_backend.core.model_providers import PROVIDERS
from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.auth.models import User
from dotrix_backend.modules.workspaces.models import Membership

from .models import UserModelKey
from .schemas import DefaultModelSave, ModelKeyRead, ModelKeySave, PersonalModelsRead


def _now() -> datetime:
    return datetime.now(UTC)


def _provider(name: str) -> str:
    if name not in PROVIDERS:
        raise NotFound(f"No provider {name!r}; use one of: {', '.join(PROVIDERS)}")
    return name


def _catalogue(settings: Settings) -> list[str]:
    return list(dict.fromkeys([*settings.models, settings.default_model]))


@dataclass
class RunKeys:
    """The instructing person's keys; no workspace or server fallback."""

    keys: dict[str, str]
    personal: set[str]  # providers whose key is the person's own


async def run_keys(
    session: AsyncSession, secrets: Secrets, workspace_id: uuid.UUID, user_id: uuid.UUID | None,
) -> RunKeys:
    """Only the instructing person's keys, including scheduled runs by their creator."""
    if user_id is None:
        return RunKeys({}, set())
    member = await session.scalar(select(Membership.id).where(
        Membership.workspace_id == workspace_id, Membership.user_id == user_id,
    ))
    keys = await PersonalKeys(session, secrets).keys(user_id) if member is not None else {}
    return RunKeys(keys, set(keys))


def may_choose(member: Membership, model: str, personal: set[str]) -> bool:
    """Picking a model other than the project's: people the workspace lets choose, or anyone
    whose own key pays for it."""
    from dotrix_backend.modules.workspaces.permissions import Permission, can

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
            if plain and plain.strip():
                out[provider] = plain.strip()
        return out

    async def connected(self, user_id: uuid.UUID) -> set[str]:
        return set(await self._rows(user_id))

    async def read(self, user: User, settings: Settings) -> PersonalModelsRead:
        rows = await self._rows(user.id)
        return PersonalModelsRead(
            keys=[self._read(name, rows.get(name), settings) for name in PROVIDERS],
            default_model=user.default_model,
            default_coding_tool=user.default_coding_tool,
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
            updated_at=row.updated_at if row else None,
            limit_reached_at=row.limit_reached_at if row else None,
            limit_message=row.limit_message if row else None,
            models=[m for m in _catalogue(settings) if m.startswith(f"{provider}:")],
        )
