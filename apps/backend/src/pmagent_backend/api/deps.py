"""Shared FastAPI dependencies. Auth deps (current_user, current_workspace,
require_permission) land here with the auth module."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.db.session import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]
