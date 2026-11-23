"""Allow downstream specialist tasks to opt into partial dependency outputs."""

import sqlalchemy as sa
from alembic import op

revision = "c0d146a04605"
down_revision = "c0d146a04604"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("allow_partial_dependencies", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "allow_partial_dependencies")
