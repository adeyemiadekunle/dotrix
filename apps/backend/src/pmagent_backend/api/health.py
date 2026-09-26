from fastapi import APIRouter
from sqlalchemy import text

from .deps import SessionDep

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def live() -> dict[str, str]:
    """Liveness: the process is up. Never touches dependencies."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(session: SessionDep) -> dict[str, str]:
    """Readiness: the database is reachable."""
    await session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}
