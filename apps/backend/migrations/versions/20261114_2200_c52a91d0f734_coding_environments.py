"""Versioned project cloud profiles and immutable run snapshots."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c52a91d0f734"
down_revision = "a7d4c9e2b861"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("projects", sa.Column("coding_environment", postgresql.JSONB(none_as_null=True), nullable=True))
    op.add_column("coding_runs", sa.Column("environment_snapshot", postgresql.JSONB(none_as_null=True), nullable=True))


def downgrade():
    op.drop_column("coding_runs", "environment_snapshot")
    op.drop_column("projects", "coding_environment")
