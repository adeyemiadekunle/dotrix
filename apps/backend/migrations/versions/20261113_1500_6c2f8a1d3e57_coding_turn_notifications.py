"""Notifications when a coding turn ends

Revision ID: 6c2f8a1d3e57
Revises: 3d8a5f1c7b29
Create Date: 2026-11-13 15:00:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = "6c2f8a1d3e57"
down_revision: str | None = "3d8a5f1c7b29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = "'approval', 'checkpoint', 'assigned', 'finding', 'mention', 'decided', 'watching', 'limit', 'stale'"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_notifications_notificationkind"), "notifications", type_="check")
    op.create_check_constraint(
        op.f("ck_notifications_notificationkind"), "notifications", f"kind IN ({_BEFORE}, 'coding')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE kind = 'coding'")
    op.drop_constraint(op.f("ck_notifications_notificationkind"), "notifications", type_="check")
    op.create_check_constraint(op.f("ck_notifications_notificationkind"), "notifications", f"kind IN ({_BEFORE})")
