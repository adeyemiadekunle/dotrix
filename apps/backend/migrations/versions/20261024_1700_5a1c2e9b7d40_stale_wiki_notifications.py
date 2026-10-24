"""Notifications for wiki pages a push made stale

Revision ID: 5a1c2e9b7d40
Revises: 3fd838d80ac2
Create Date: 2026-10-24 17:00:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = "5a1c2e9b7d40"
down_revision: str | None = "3fd838d80ac2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = "'approval', 'checkpoint', 'assigned', 'finding', 'mention', 'decided', 'watching', 'limit'"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_notifications_notificationkind"), "notifications", type_="check")
    op.create_check_constraint(
        op.f("ck_notifications_notificationkind"), "notifications", f"kind IN ({_BEFORE}, 'stale')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE kind = 'stale'")
    op.drop_constraint(op.f("ck_notifications_notificationkind"), "notifications", type_="check")
    op.create_check_constraint(op.f("ck_notifications_notificationkind"), "notifications", f"kind IN ({_BEFORE})")
