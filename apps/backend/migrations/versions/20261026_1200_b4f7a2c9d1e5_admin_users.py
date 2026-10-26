"""Admin accounts: the Admin app's own users, bound to a workspace by a proven owner.

Revision ID: b4f7a2c9d1e5
Revises: 92a31cd6ef04
"""
import sqlalchemy as sa
from alembic import op

revision: str = "b4f7a2c9d1e5"
down_revision: str | None = "92a31cd6ef04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_admin_users_workspace_id", "admin_users", ["workspace_id"])
    op.create_index("ix_admin_users_user_id", "admin_users", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_admin_users_user_id", table_name="admin_users")
    op.drop_index("ix_admin_users_workspace_id", table_name="admin_users")
    op.drop_table("admin_users")
