"""Provider access is personal in every workspace."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Request

from dotrix_backend.api.deps import CurrentUser, SessionDep

from .service import run_keys


async def personal_providers(workspace_id: uuid.UUID, session: SessionDep, user: CurrentUser, request: Request) -> set[str]:
    keys = await run_keys(session, request.app.state.secrets, workspace_id, user.id)
    return set(keys.keys)


Personal = Annotated[set[str], Depends(personal_providers)]


Connected = Personal
