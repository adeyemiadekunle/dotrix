"""Rename shared workspaces to Team."""

from alembic import op

revision = "c0d146a04606"
down_revision = "c0d146a04605"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("workspacekind", "workspaces", type_="check")
    op.execute("UPDATE workspaces SET kind = 'team' WHERE kind = 'organization'")
    op.create_check_constraint("workspacekind", "workspaces", "kind IN ('personal', 'team')")


def downgrade() -> None:
    op.drop_constraint("workspacekind", "workspaces", type_="check")
    op.execute("UPDATE workspaces SET kind = 'organization' WHERE kind = 'team'")
    op.create_check_constraint("workspacekind", "workspaces", "kind IN ('personal', 'organization')")
