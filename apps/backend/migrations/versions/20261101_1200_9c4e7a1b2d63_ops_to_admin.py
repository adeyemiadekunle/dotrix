"""Rename the retired ops identity tables for the admin console.

Revision ID: 9c4e7a1b2d63
Revises: 8b3f1d6e2a90
"""
from alembic import op

revision = "9c4e7a1b2d63"
down_revision = "8b3f1d6e2a90"
branch_labels = None
depends_on = None


def _rename(old: str, new: str) -> None:
    op.execute(f'ALTER TABLE "{old}" RENAME TO "{new}"')


def _rename_constraint(table: str, old: str, new: str) -> None:
    op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{old}" TO "{new}"')


def _rename_index(old: str, new: str) -> None:
    op.execute(f'ALTER INDEX "{old}" RENAME TO "{new}"')


def upgrade() -> None:
    _rename("ops_users", "admin_users")
    _rename("ops_sessions", "admin_sessions")
    op.execute('ALTER TABLE admin_sessions RENAME COLUMN ops_user_id TO admin_user_id')
    for old, new in (
        ("pk_ops_users", "pk_admin_users"),
        ("uq_ops_users_email", "uq_admin_users_email"),
        ("fk_ops_users_workspace_id_workspaces", "fk_admin_users_workspace_id_workspaces"),
        ("fk_ops_users_user_id_users", "fk_admin_users_user_id_users"),
        ("pk_ops_sessions", "pk_admin_sessions"),
        ("uq_ops_sessions_token_hash", "uq_admin_sessions_token_hash"),
        ("fk_ops_sessions_ops_user_id_ops_users", "fk_admin_sessions_admin_user_id_admin_users"),
    ):
        _rename_constraint("admin_users" if "users" in old and "sessions" not in old else "admin_sessions", old, new)
    for old, new in (
        ("ix_ops_users_workspace_id", "ix_admin_users_workspace_id"),
        ("ix_ops_users_user_id", "ix_admin_users_user_id"),
        ("ix_ops_sessions_ops_user_id", "ix_admin_sessions_admin_user_id"),
    ):
        _rename_index(old, new)


def downgrade() -> None:
    for old, new in (
        ("ix_admin_users_workspace_id", "ix_ops_users_workspace_id"),
        ("ix_admin_users_user_id", "ix_ops_users_user_id"),
        ("ix_admin_sessions_admin_user_id", "ix_ops_sessions_ops_user_id"),
    ):
        _rename_index(old, new)
    for table, old, new in (
        ("admin_users", "pk_admin_users", "pk_ops_users"),
        ("admin_users", "uq_admin_users_email", "uq_ops_users_email"),
        ("admin_users", "fk_admin_users_workspace_id_workspaces", "fk_ops_users_workspace_id_workspaces"),
        ("admin_users", "fk_admin_users_user_id_users", "fk_ops_users_user_id_users"),
        ("admin_sessions", "pk_admin_sessions", "pk_ops_sessions"),
        ("admin_sessions", "uq_admin_sessions_token_hash", "uq_ops_sessions_token_hash"),
        ("admin_sessions", "fk_admin_sessions_admin_user_id_admin_users", "fk_ops_sessions_ops_user_id_ops_users"),
    ):
        _rename_constraint(table, old, new)
    op.execute('ALTER TABLE admin_sessions RENAME COLUMN admin_user_id TO ops_user_id')
    _rename("admin_sessions", "ops_sessions")
    _rename("admin_users", "ops_users")
