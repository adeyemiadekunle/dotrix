"""workspace rules and watching

Revision ID: 68afe9d5d466
Revises: 9c5d0aa607be
Create Date: 2026-10-02 21:02:03.783395
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "68afe9d5d466"
down_revision: str | None = "9c5d0aa607be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_rules",
        sa.Column("handle", sa.String(length=31), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name=op.f("fk_workspace_rules_updated_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_rules_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_rules")),
        sa.UniqueConstraint(
            "workspace_id", "handle", name=op.f("uq_workspace_rules_workspace_id_handle")
        ),
    )
    op.create_index(
        op.f("ix_workspace_rules_workspace_id"), "workspace_rules", ["workspace_id"], unique=False
    )
    # A new kind: watchers hear about changes to the issues they watch.
    op.drop_constraint(op.f("ck_notifications_notificationkind"), "notifications", type_="check")
    op.create_check_constraint(
        op.f("ck_notifications_notificationkind"), "notifications",
        "kind IN ('approval', 'checkpoint', 'assigned', 'finding', 'mention', 'decided', 'watching')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE kind = 'watching'")
    op.drop_constraint(op.f("ck_notifications_notificationkind"), "notifications", type_="check")
    op.create_check_constraint(
        op.f("ck_notifications_notificationkind"), "notifications",
        "kind IN ('approval', 'checkpoint', 'assigned', 'finding', 'mention', 'decided')",
    )
    op.drop_index(op.f("ix_workspace_rules_workspace_id"), table_name="workspace_rules")
    op.drop_table("workspace_rules")
