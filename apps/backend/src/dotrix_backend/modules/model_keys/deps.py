"""The providers a workspace has its own keys for, for routes that list runnable models."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select

from dotrix_backend.api.deps import CurrentUser, SessionDep

from .models import UserModelKey, WorkspaceModelKey
from .service import personal_keys_allowed


async def personal_providers(workspace_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> set[str]:
    """The providers your own keys cover here (none where the workspace doesn't allow them)."""
    if not await personal_keys_allowed(session, workspace_id):
        return set()
    return set(await session.scalars(select(UserModelKey.provider).where(UserModelKey.user_id == user.id)))


Personal = Annotated[set[str], Depends(personal_providers)]


async def connected_providers(workspace_id: uuid.UUID, session: SessionDep, personal: Personal) -> set[str]:
    """The providers with a key here for you: the workspace's, and your own where allowed."""
    rows = set(await session.scalars(
        select(WorkspaceModelKey.provider).where(WorkspaceModelKey.workspace_id == workspace_id)
    ))
    return rows | personal


Connected = Annotated[set[str], Depends(connected_providers)]
