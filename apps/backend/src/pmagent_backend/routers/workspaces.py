"""Workspaces, members, roles, invites (FR-2, FR-3, FR-4)."""
from fastapi import APIRouter

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
