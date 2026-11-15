"""Versioned project cloud setup, pinned before approval; never applied to native runners."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class EnvironmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    enabled: bool = False
    name: str = Field(default="Project environment", min_length=1, max_length=100)
    image: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}$")] | None = None
    setup_script: str = Field(default="", max_length=16000)
    verify_script: str = Field(default="", max_length=16000)
    timeout_seconds: int = Field(default=300, ge=10, le=900)


class EnvironmentRead(EnvironmentUpdate):
    image_policy: Literal["platform", "approved"] = "platform"
    available_images: list[str] = Field(default_factory=list)


def profile(value: dict | None) -> EnvironmentRead:
    result = EnvironmentRead.model_validate(value or {"revision": 0})
    return result.model_copy(update={"image_policy": "approved" if result.image else "platform"})


def require_approved_image(image: str | None, approved: list[str]) -> None:
    from dotrix_backend.core.errors import Conflict

    if image is not None and image not in approved:
        raise Conflict("This coding image is not approved by the server operator; choose an approved image")
