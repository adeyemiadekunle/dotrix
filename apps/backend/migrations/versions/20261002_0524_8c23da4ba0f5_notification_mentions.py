"""notification mentions

Revision ID: 8c23da4ba0f5
Revises: 4d6240e95747
Create Date: 2026-10-02 05:24:20.264290
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8c23da4ba0f5"
down_revision: str | None = "4d6240e95747"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("excerpt", sa.String(length=300), nullable=True))
    op.drop_constraint(op.f("ck_notifications_notificationkind"), "notifications", type_="check")
    op.create_check_constraint(
        "notificationkind", "notifications", "kind IN ('approval', 'checkpoint', 'assigned', 'finding', 'mention')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE kind = 'mention'")
    op.drop_constraint(op.f("ck_notifications_notificationkind"), "notifications", type_="check")
    op.create_check_constraint(
        "notificationkind", "notifications", "kind IN ('approval', 'checkpoint', 'assigned', 'finding')"
    )
    op.drop_column("notifications", "excerpt")
