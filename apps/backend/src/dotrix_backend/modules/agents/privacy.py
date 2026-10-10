"""Whose a conversation is: a person's runs are theirs alone (decided 2026-10-09).

In a personal workspace that's simply the owner. In an organisation, colleagues — owners and
admins included — don't see each other's conversations; what an agent changed is still public
(documents, issues, the activity of decisions, the audit log). Two exceptions:
- an automation's runs, which belong to the workspace, are also seen by owners and admins;
- someone who may approve agents' changes can open a run while it waits for a decision, so
  they can see what they're deciding.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import or_

from dotrix_backend.modules.workspaces.models import Membership
from dotrix_backend.modules.workspaces.permissions import Permission, can

from .models import AgentRun, RunStatus


def runs_visible_to(member: Membership) -> Any:
    """The runs `member` sees in lists, threads, and the activity feed."""
    clause = AgentRun.requested_by_id == member.user_id
    if can(member, Permission.MANAGE_WORKSPACE):
        clause = or_(clause, AgentRun.automation_id.is_not(None))
    return clause


def run_openable_by(member: Membership) -> Any:
    """The runs `member` may open one by one: theirs, and those waiting on a decision they may make."""
    clause = runs_visible_to(member)
    if can(member, Permission.APPROVE_ACTIONS):
        clause = or_(clause, AgentRun.status == RunStatus.AWAITING_APPROVAL)
    return clause
