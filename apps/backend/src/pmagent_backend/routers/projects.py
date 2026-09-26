"""Projects, connectors, and .pmagent/ sync (FR-9, FR-10, FR-18)."""
from fastapi import APIRouter

router = APIRouter(prefix="/projects", tags=["projects"])
