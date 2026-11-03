"""Keep the submitted baseline digest separate from the resulting human-context revision."""
import sqlalchemy as sa
from alembic import op

revision = "b50e1a9c7632"
down_revision = "d40a7c2e9186"
branch_labels = depends_on = None


def upgrade():
    op.add_column("repo_baseline_reviews", sa.Column("request_digest", sa.String(64), nullable=True))
    op.execute("UPDATE repo_baseline_reviews SET request_digest = digest")


def downgrade():
    op.drop_column("repo_baseline_reviews", "request_digest")
