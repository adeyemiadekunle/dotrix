"""The providers a workspace has its own keys for, for routes that list runnable models."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select

from pmagent_backend.api.deps import SessionDep

from .models import WorkspaceModelKey


async def connected_providers(workspace_id: uuid.UUID, session: SessionDep) -> set[str]:
    rows = await session.scalars(select(WorkspaceModelKey.provider).where(WorkspaceModelKey.workspace_id == workspace_id))
    return set(rows)


Connected = Annotated[set[str], Depends(connected_providers)]
