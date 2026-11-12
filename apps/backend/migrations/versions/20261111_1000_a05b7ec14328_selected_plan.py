"""Pin the selected plan on each Build request."""
import sqlalchemy as sa
from alembic import op

revision = "a05b7ec14328"
down_revision = "f94a6db03217"
branch_labels = depends_on = None


def upgrade():
    op.add_column("agent_runs", sa.Column("selected_plan_id", sa.Uuid(), nullable=True))


def downgrade():
    op.drop_column("agent_runs", "selected_plan_id")
