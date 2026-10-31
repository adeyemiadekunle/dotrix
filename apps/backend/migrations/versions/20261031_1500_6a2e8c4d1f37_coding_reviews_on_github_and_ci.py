"""Coding runs: Juno's review posted on GitHub, and CI on the turn's commit."""
import sqlalchemy as sa
from alembic import op

revision = "6a2e8c4d1f37"
down_revision = "3c7d9e1f5a42"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("coding_runs", sa.Column("review_posted_url", sa.String(300), nullable=True))
    op.add_column("coding_runs", sa.Column("ci_state", sa.String(16), nullable=True))
    op.add_column("coding_runs", sa.Column("ci_sha", sa.String(40), nullable=True))
    op.add_column("coding_runs", sa.Column("ci_review_run_id", sa.Uuid(), nullable=True))
    op.add_column("coding_runs", sa.Column("ci_review_posted_url", sa.String(300), nullable=True))


def downgrade():
    for column in ("ci_review_posted_url", "ci_review_run_id", "ci_sha", "ci_state", "review_posted_url"):
        op.drop_column("coding_runs", column)
