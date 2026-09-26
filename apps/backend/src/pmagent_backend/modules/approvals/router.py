"""Action Mode approvals and the audit log (FR-5, FR-36)."""
from fastapi import APIRouter

router = APIRouter(prefix="/approvals", tags=["approvals"])
