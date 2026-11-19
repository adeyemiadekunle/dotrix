"""Personal Code Mode preference and pinned Nova turn choice.

Revision ID: a7d4c9e2b861
Revises: 9e4b7c2a1f60
"""
import sqlalchemy as sa
from alembic import op

revision = "a7d4c9e2b861"
down_revision = "9e4b7c2a1f60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("code_mode_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("agent_runs", sa.Column("scripts_enabled", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_runs", "scripts_enabled")
    op.drop_column("users", "code_mode_enabled")
