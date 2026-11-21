"""Bind managed local worktrees to their original runner."""

import sqlalchemy as sa
from alembic import op

revision = "c0d146a04603"
down_revision = "c0d146a04602"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("coding_sessions", sa.Column("local_worktree_runner_id", sa.Uuid()))


def downgrade() -> None:
    op.drop_column("coding_sessions", "local_worktree_runner_id")
