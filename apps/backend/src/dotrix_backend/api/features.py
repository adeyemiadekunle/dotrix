"""What this server offers, so clients show only what works here. No sign-in needed: the
sign-in and onboarding pages read it too, and it says nothing about anyone's data."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .deps import SettingsDep

router = APIRouter(prefix="/features", tags=["features"])


class Features(BaseModel):
    organisations: bool = Field(
        description="Organisation workspaces (teams: invites, roles, members) can be created and opened. "
        "When false, only personal workspaces are listed and the API refuses organisations."
    )


@router.get("")
async def get_features(settings: SettingsDep) -> Features:
    """What this server offers (`DOTRIX_ORGANISATIONS`: off on a deployed server unless turned on)."""
    return Features(organisations=settings.organisations_enabled)
