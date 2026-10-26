"""Rename historical admin identity tables to ops without losing sessions.

Revision ID: e5a9c3b2d716
Revises: c8e5d3a6f2b1
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "e5a9c3b2d716"
down_revision: str | None = "c8e5d3a6f2b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())
    # Earlier previews ran these IDs after the migration files had already been
    # edited to create ops_* directly. Keep those installations untouched.
    if {"ops_users", "ops_sessions"} <= tables and not {"admin_users", "admin_sessions"} & tables:
        return
    if not {"admin_users", "admin_sessions"} <= tables or {"ops_users", "ops_sessions"} & tables:
        raise RuntimeError("Expected either admin_* or ops_* tables; refusing to alter a mixed schema")

    op.rename_table("admin_users", "ops_users")
    op.rename_table("admin_sessions", "ops_sessions")
    op.alter_column("ops_sessions", "admin_user_id", new_column_name="ops_user_id", existing_type=sa.Uuid())
    for old, new in (
        ("pk_admin_users", "pk_ops_users"),
        ("uq_admin_users_email", "uq_ops_users_email"),
        ("fk_admin_users_user_id_users", "fk_ops_users_user_id_users"),
        ("fk_admin_users_workspace_id_workspaces", "fk_ops_users_workspace_id_workspaces"),
    ):
        op.execute(sa.text(f"ALTER TABLE ops_users RENAME CONSTRAINT {old} TO {new}"))
    for old, new in (
        ("pk_admin_sessions", "pk_ops_sessions"),
        ("uq_admin_sessions_token_hash", "uq_ops_sessions_token_hash"),
        ("fk_admin_sessions_admin_user_id_admin_users", "fk_ops_sessions_ops_user_id_ops_users"),
    ):
        op.execute(sa.text(f"ALTER TABLE ops_sessions RENAME CONSTRAINT {old} TO {new}"))
    for old, new in (
        ("ix_admin_users_workspace_id", "ix_ops_users_workspace_id"),
        ("ix_admin_users_user_id", "ix_ops_users_user_id"),
        ("ix_admin_sessions_admin_user_id", "ix_ops_sessions_ops_user_id"),
    ):
        op.execute(sa.text(f"ALTER INDEX {old} RENAME TO {new}"))


def downgrade() -> None:
    for old, new in (
        ("ix_ops_users_workspace_id", "ix_admin_users_workspace_id"),
        ("ix_ops_users_user_id", "ix_admin_users_user_id"),
        ("ix_ops_sessions_ops_user_id", "ix_admin_sessions_admin_user_id"),
    ):
        op.execute(sa.text(f"ALTER INDEX {old} RENAME TO {new}"))
    for old, new in (
        ("pk_ops_users", "pk_admin_users"),
        ("uq_ops_users_email", "uq_admin_users_email"),
        ("fk_ops_users_user_id_users", "fk_admin_users_user_id_users"),
        ("fk_ops_users_workspace_id_workspaces", "fk_admin_users_workspace_id_workspaces"),
    ):
        op.execute(sa.text(f"ALTER TABLE ops_users RENAME CONSTRAINT {old} TO {new}"))
    for old, new in (
        ("pk_ops_sessions", "pk_admin_sessions"),
        ("uq_ops_sessions_token_hash", "uq_admin_sessions_token_hash"),
        ("fk_ops_sessions_ops_user_id_ops_users", "fk_admin_sessions_admin_user_id_admin_users"),
    ):
        op.execute(sa.text(f"ALTER TABLE ops_sessions RENAME CONSTRAINT {old} TO {new}"))
    op.alter_column("ops_sessions", "ops_user_id", new_column_name="admin_user_id", existing_type=sa.Uuid())
    op.rename_table("ops_sessions", "admin_sessions")
    op.rename_table("ops_users", "admin_users")
