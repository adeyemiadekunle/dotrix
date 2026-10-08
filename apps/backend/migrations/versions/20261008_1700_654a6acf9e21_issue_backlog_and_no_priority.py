"""issue status backlog and priority none

Revision ID: 654a6acf9e21
Revises: 72dad5d930d0
Create Date: 2026-10-08 17:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "654a6acf9e21"
down_revision: str | None = "72dad5d930d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = "'todo', 'in_progress', 'blocked', 'review', 'done'"
PRIORITIES = "'low', 'medium', 'high', 'urgent'"


def _checks(statuses: str, priorities: str) -> None:
    op.drop_constraint(op.f("ck_issues_issuestatus"), "issues", type_="check")
    op.create_check_constraint(op.f("ck_issues_issuestatus"), "issues", f"status IN ({statuses})")
    op.drop_constraint(op.f("ck_issues_priority"), "issues", type_="check")
    op.create_check_constraint(op.f("ck_issues_priority"), "issues", f"priority IN ({priorities})")


def upgrade() -> None:
    _checks(f"'backlog', {STATUSES}", f"{PRIORITIES}, 'none'")


def downgrade() -> None:
    op.execute("UPDATE issues SET status = 'todo' WHERE status = 'backlog'")
    op.execute("UPDATE issues SET priority = 'medium' WHERE priority = 'none'")
    _checks(STATUSES, PRIORITIES)
