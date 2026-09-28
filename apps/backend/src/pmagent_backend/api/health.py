import time
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from .deps import SessionDep

router = APIRouter(prefix="/health", tags=["health"])

# When this process started (for uptime); set once, at import.
_STARTED = time.monotonic()


class Health(BaseModel):
    status: str = Field(description='"ok"')
    time: datetime = Field(description="The server's clock, in UTC")
    uptime_seconds: int = Field(description="How long this API process has been running")
    version: str = Field(description="The API version")


class Readiness(BaseModel):
    status: str = Field(description='"ok"')
    time: datetime = Field(description="The server's clock, in UTC")
    database: str = Field(description='"ok" when the database answered')
    database_ms: float = Field(description="How long the database took to answer, in milliseconds")


@router.get("")
async def health_live(request: Request) -> Health:
    """Liveness: the process is up, with the server's time. Never touches dependencies."""
    return Health(
        status="ok",
        time=datetime.now(UTC),
        uptime_seconds=int(time.monotonic() - _STARTED),
        version=request.app.version,
    )


@router.get("/ready")
async def health_ready(session: SessionDep) -> Readiness:
    """Readiness: the database is reachable (and how quickly it answered)."""
    started = time.perf_counter()
    await session.execute(text("SELECT 1"))
    return Readiness(
        status="ok",
        time=datetime.now(UTC),
        database="ok",
        database_ms=round((time.perf_counter() - started) * 1000, 1),
    )
