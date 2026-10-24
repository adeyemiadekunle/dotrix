"""Coding turns accepted before they're pushed (Manual), and reverts of pushed turns.

Revision ID: 0c7ab3cdd5e7
Revises: ac5d493b1551
Create Date: 2026-10-24 19:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0c7ab3cdd5e7"
down_revision: str | None = "ac5d493b1551"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STATUSES = (
    "awaiting_approval", "rejected", "queued", "running", "pr_opened",
    "no_changes", "failed", "stopped", "recovery_required",
)
NEW_STATUSES = (*OLD_STATUSES, "changes_ready")


def _status_check(values: tuple[str, ...]) -> str:
    return "status IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    op.add_column("coding_runs", sa.Column("pending_patch", sa.Text(), nullable=True))
    op.add_column("coding_runs", sa.Column("accepted_by_id", sa.Uuid(), nullable=True))
    op.add_column("coding_runs", sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("coding_runs", sa.Column("revert_of", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_coding_runs_revert_of_coding_runs"), "coding_runs", "coding_runs",
        ["revert_of"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_coding_runs_accepted_by_id_users"), "coding_runs", "users",
        ["accepted_by_id"], ["id"], ondelete="SET NULL",
    )
    op.drop_constraint(op.f("ck_coding_runs_codingrunstatus"), "coding_runs", type_="check")
    op.create_check_constraint(op.f("ck_coding_runs_codingrunstatus"), "coding_runs", _status_check(NEW_STATUSES))


def downgrade() -> None:
    # Changes that never got accepted are discarded: nothing of them reached GitHub.
    op.execute(
        "UPDATE coding_runs SET status = 'stopped', finished_at = now(), "
        "error = 'Discarded: its changes were never accepted' WHERE status = 'changes_ready'"
    )
    op.drop_constraint(op.f("ck_coding_runs_codingrunstatus"), "coding_runs", type_="check")
    op.create_check_constraint(op.f("ck_coding_runs_codingrunstatus"), "coding_runs", _status_check(OLD_STATUSES))
    op.drop_constraint(op.f("fk_coding_runs_accepted_by_id_users"), "coding_runs", type_="foreignkey")
    op.drop_constraint(op.f("fk_coding_runs_revert_of_coding_runs"), "coding_runs", type_="foreignkey")
    op.drop_column("coding_runs", "revert_of")
    op.drop_column("coding_runs", "accepted_at")
    op.drop_column("coding_runs", "accepted_by_id")
    op.drop_column("coding_runs", "pending_patch")
