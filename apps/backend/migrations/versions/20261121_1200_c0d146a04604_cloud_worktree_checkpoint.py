"""Keep an encrypted cloud checkout checkpoint for recovery of a turn."""

import sqlalchemy as sa
from alembic import op

revision = "c0d146a04604"
down_revision = "c0d146a04603"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("coding_runs", sa.Column("cloud_checkpoint", sa.Text()))


def downgrade() -> None:
    op.drop_column("coding_runs", "cloud_checkpoint")
