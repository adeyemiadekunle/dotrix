"""Ops becomes platform-scoped: workspace/user links become optional.

Revision ID: f2b8d4e6a937
Revises: e5a9c3b2d716
"""
import sqlalchemy as sa
from alembic import op

revision: str = "f2b8d4e6a937"
down_revision: str | None = "e5a9c3b2d716"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("fk_ops_users_workspace_id_workspaces", "ops_users", type_="foreignkey")
    op.drop_constraint("fk_ops_users_user_id_users", "ops_users", type_="foreignkey")
    op.alter_column("ops_users", "workspace_id", existing_type=sa.Uuid(), nullable=True)
    op.alter_column("ops_users", "user_id", existing_type=sa.Uuid(), nullable=True)
    op.create_foreign_key(
        "fk_ops_users_workspace_id_workspaces", "ops_users", "workspaces", ["workspace_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_ops_users_user_id_users", "ops_users", "users", ["user_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("fk_ops_users_user_id_users", "ops_users", type_="foreignkey")
    op.drop_constraint("fk_ops_users_workspace_id_workspaces", "ops_users", type_="foreignkey")
    op.alter_column("ops_users", "user_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column("ops_users", "workspace_id", existing_type=sa.Uuid(), nullable=False)
    op.create_foreign_key(
        "fk_ops_users_user_id_users", "ops_users", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_ops_users_workspace_id_workspaces", "ops_users", "workspaces", ["workspace_id"], ["id"], ondelete="CASCADE"
    )
