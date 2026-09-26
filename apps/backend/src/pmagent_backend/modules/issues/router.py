"""Jira-style issues, board, backlog, sprints (FR-29 to FR-33)."""
from fastapi import APIRouter

router = APIRouter(prefix="/issues", tags=["issues"])
