"""Record coding workspace and uncertain worker outcomes.

Revision ID: 71b9e2a4f603
Revises: c7e91b4a62d0
Create Date: 2026-10-22 13:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "71b9e2a4f603"
down_revision: str | None = "c7e91b4a62d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STATUSES = (
    "awaiting_approval", "rejected", "queued", "running", "pr_opened",
    "no_changes", "failed", "stopped",
)
NEW_STATUSES = (*OLD_STATUSES, "recovery_required")


def _status_check(values: tuple[str, ...]) -> str:
    return "status IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    op.add_column("coding_runs", sa.Column("workspace_path", sa.String(1024), nullable=True))
    op.drop_constraint(op.f("ck_coding_runs_codingrunstatus"), "coding_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_coding_runs_codingrunstatus"), "coding_runs", _status_check(NEW_STATUSES),
    )


def downgrade() -> None:
    # Preserve an explanation when reverting to a schema without the distinct state.
    op.execute(
        "UPDATE coding_runs SET status = 'failed', "
        "error = COALESCE(error, 'Recovery required before downgrade') "
        "WHERE status = 'recovery_required'"
    )
    op.drop_constraint(op.f("ck_coding_runs_codingrunstatus"), "coding_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_coding_runs_codingrunstatus"), "coding_runs", _status_check(OLD_STATUSES),
    )
    op.drop_column("coding_runs", "workspace_path")
