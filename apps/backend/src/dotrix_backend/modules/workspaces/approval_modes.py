"""Approval modes: how much an agent may do on a person's instruction before a person looks.

One setting for chat and coding, like Claude Code's permission modes:
- **Manual**: every change waits for a yes; a coding turn waits to start.
- **Accept edits**: what the person asked for goes through (their instruction is the approval,
  recorded as theirs): changes inside dotrix (documents, issues, comments, graph links), and a
  coding turn starts at once (the PR stays the review point; agents never merge).
- **Auto**: the same, and a pipeline's checkpoints don't pause the run.

The mode a run gets is the lowest of what was asked for, the workspace's cap (owners set it;
pausing changes without approval puts everyone back on Manual), and the person's own: someone
who may not approve agent changes is always on Manual. Whatever the mode, a change still needs
the person to be allowed to make it, an owner's "block" still blocks, and closing issues,
merging, and agent rules and contracts always need a person.
"""
from __future__ import annotations

import enum
from typing import Any

from .models import WorkspaceKind
from .permissions import Permission, can


class ApprovalMode(enum.StrEnum):
    MANUAL = "manual"
    ACCEPT_EDITS = "accept_edits"
    AUTO = "auto"


_ORDER = list(ApprovalMode)


def cap_of(workspace: Any) -> ApprovalMode:
    """The highest mode the workspace allows: its owners' choice, else Auto for a personal
    workspace (it's its owner's) and Manual for an organisation. Paused: Manual."""
    if workspace.unattended_paused:
        return ApprovalMode.MANUAL
    if workspace.approval_mode_cap is not None:
        return ApprovalMode(workspace.approval_mode_cap)
    return ApprovalMode.AUTO if workspace.kind is WorkspaceKind.PERSONAL else ApprovalMode.MANUAL


def default_of(workspace: Any) -> ApprovalMode:
    """What a new conversation or session starts on in the app: Accept edits in a personal
    workspace, Manual in an organisation (never above the cap)."""
    wanted = ApprovalMode.ACCEPT_EDITS if workspace.kind is WorkspaceKind.PERSONAL else ApprovalMode.MANUAL
    return lowest(wanted, cap_of(workspace))


def rank(mode: ApprovalMode) -> int:
    return _ORDER.index(mode)


def lowest(*modes: ApprovalMode) -> ApprovalMode:
    return min(modes, key=_ORDER.index)


def effective(requested: ApprovalMode | None, member: Any) -> ApprovalMode:
    """The mode `member` gets for `requested` (None: Manual, as before approval modes) here."""
    if requested is None or requested is ApprovalMode.MANUAL:
        return ApprovalMode.MANUAL
    if not can(member, Permission.APPROVE_ACTIONS):
        return ApprovalMode.MANUAL
    return lowest(requested, cap_of(member.workspace))


def goes_through(mode: ApprovalMode | None) -> bool:
    """Whether what the person asked for goes through without waiting (Accept edits or Auto)."""
    return mode in (ApprovalMode.ACCEPT_EDITS, ApprovalMode.AUTO)
