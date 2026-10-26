"""Ops sessions: rotating refresh tokens for the Ops app.

Revision ID: c8e5d3a6f2b1
Revises: b4f7a2c9d1e5
"""
import sqlalchemy as sa
from alembic import op

revision: str = "c8e5d3a6f2b1"
down_revision: str | None = "b4f7a2c9d1e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ops_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ops_user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["ops_user_id"], ["ops_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_ops_sessions_ops_user_id", "ops_sessions", ["ops_user_id"])


def downgrade() -> None:
    op.drop_index("ix_ops_sessions_ops_user_id", table_name="ops_sessions")
    op.drop_table("ops_sessions")
