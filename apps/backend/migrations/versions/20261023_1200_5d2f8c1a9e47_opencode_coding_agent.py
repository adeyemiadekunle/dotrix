"""OpenCode as a coding agent.

Revision ID: 5d2f8c1a9e47
Revises: 71b9e2a4f603
Create Date: 2026-10-23 12:00:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = "5d2f8c1a9e47"
down_revision: str | None = "71b9e2a4f603"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_AGENTS = ("claude-code", "codex")
NEW_AGENTS = (*OLD_AGENTS, "opencode")
TABLES = ("coding_runs", "coding_sessions")


def _agent_check(values: tuple[str, ...]) -> str:
    return "agent IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def _replace(values: tuple[str, ...]) -> None:
    for table in TABLES:
        op.drop_constraint(op.f(f"ck_{table}_codingagent"), table, type_="check")
        op.create_check_constraint(op.f(f"ck_{table}_codingagent"), table, _agent_check(values))


def upgrade() -> None:
    _replace(NEW_AGENTS)


def downgrade() -> None:
    # No older agent can stand in for OpenCode's runs and sessions: refuse rather than relabel them.
    for table in TABLES:
        op.execute(
            f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM {table} WHERE agent = 'opencode') THEN "
            f"RAISE EXCEPTION '{table} has OpenCode rows; delete them before downgrading'; END IF; END $$"
        )
    _replace(OLD_AGENTS)
