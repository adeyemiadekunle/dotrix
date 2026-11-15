"""Immutable resolved Docker image identity per coding turn."""
import sqlalchemy as sa
from alembic import op

revision = "e47b209c6a18"
down_revision = "c52a91d0f734"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("coding_runs", sa.Column("environment_image_id", sa.String(80), nullable=True))


def downgrade():
    op.drop_column("coding_runs", "environment_image_id")
