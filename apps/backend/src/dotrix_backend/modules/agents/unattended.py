"""Changes agents make without a person approving them at the time: an owner's standing rule.

An agent's contract can allow actions (catalog.ACTIONS) without asking. Before a run starts,
`effective_specs` turns allow back into ask where the run may not use it: the workspace paused
them, a briefing, an automation without its own switch (beyond the low-risk actions), the person
who instructed the run couldn't make that change themselves, or the version's author is no
longer an owner. During the run, `Unattended.grant` says whether one change may go through: the
rule's author is recorded as its approver, with the rule (agent, action, version), and a cap per
run step and per workspace per day stops the rest (a workspace past its daily cap runs with every
change asking, as if paused).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.modules.audit.models import AuditEvent
from dotrix_backend.modules.workspaces.models import Membership, Role
from dotrix_backend.modules.workspaces.permissions import Permission, can
from dotrix_engine.catalog import ACTIONS, LOW_RISK_ACTIONS
from dotrix_engine.contracts import AgentPolicy, AgentSpec

# What the instructing person must be able to do themselves for an agent to do it unasked.
_NEEDS: dict[str, Permission] = {
    "knowledge.write": Permission.EDIT_KNOWLEDGE,
    "issues.create": Permission.EDIT_ISSUES,
    "issues.update": Permission.EDIT_ISSUES,
    "issues.comment": Permission.EDIT_ISSUES,
    "graph.link": Permission.EDIT_KNOWLEDGE,
}

REFUSED = "Changes need a person's instruction and approval"


def effective_specs(
    specs: list[AgentSpec],
    *,
    authors: dict[str, Membership | None],
    instructor: Membership | None,
    paused: bool,
    briefing: bool,
    automation: bool | None,
) -> list[AgentSpec]:
    """The contracts with every allow this run may not use turned back into ask.

    `authors`: each agent's version author's membership here (None: gone, or a built-in);
    `automation`: None for a person's run, else whether the automation may act unattended."""
    out = []
    for spec in specs:
        drop: set[str] = set()
        if paused or briefing or instructor is None:
            drop = set(ACTIONS)
        else:
            author = authors.get(spec.handle)
            for action in ACTIONS:
                low = action in LOW_RISK_ACTIONS
                if (
                    (automation is False and not low)
                    or not can(instructor, _NEEDS[action])
                    or author is None
                    or (not low and author.role is not Role.OWNER)
                ):
                    drop.add(action)
        out.append(spec.asking(drop))
    return out


async def changes_today(session: AsyncSession, workspace_id: uuid.UUID) -> int:
    """Changes made under standing rules in this workspace since midnight UTC."""
    midnight = datetime.combine(datetime.now(UTC).date(), time(), tzinfo=UTC)
    return int(
        await session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.workspace_id == workspace_id,
                AuditEvent.action.like("%.allowed"),
                AuditEvent.created_at >= midnight,
            )
        )
        or 0
    )


@dataclass
class Unattended:
    """One run step's standing rules: who approved each (by agent) and how many changes are left."""

    policy: AgentPolicy
    authors: dict[str, uuid.UUID]  # agent handle -> who saved the version that allows it
    versions: dict[str, int | None]
    left: int
    made: int = field(default=0)

    def grant(self, agent: str, action: str) -> tuple[uuid.UUID, dict[str, Any]] | str:
        """(approver, rule) when `agent` may take `action` now without asking, else why not."""
        approver = self.authors.get(agent)
        if not self.policy.allowed(agent, action) or approver is None:
            return REFUSED
        if self.made >= self.left:
            return (
                f"This run reached its limit of {self.left} changes without approval; stop changing "
                "things and tell the person what's left, so they can ask again"
            )
        self.made += 1
        return approver, {"agent": agent, "action": action, "version": self.versions.get(agent)}
