"""Coding sandboxes: a session's sandbox asleep between turns, and the hosts sandboxes may reach."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "8b3f1d6e2a90"
down_revision = "6a2e8c4d1f37"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("coding_sessions", sa.Column("sandbox_handle", postgresql.JSONB(), nullable=True))
    op.add_column("coding_sessions", sa.Column("sandbox_slept_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("workspaces", sa.Column("sandbox_network", postgresql.JSONB(), nullable=True))
    op.add_column("projects", sa.Column("sandbox_network", postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column("projects", "sandbox_network")
    op.drop_column("workspaces", "sandbox_network")
    op.drop_column("coding_sessions", "sandbox_slept_at")
    op.drop_column("coding_sessions", "sandbox_handle")
