"""Record the terms accepted at signup."""

import sqlalchemy as sa
from alembic import op

revision = "c0d146a04607"
down_revision = "c0d146a04606"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("terms_version", sa.String(32), nullable=True))
    op.add_column("users", sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "terms_accepted_at")
    op.drop_column("users", "terms_version")
