"""Retain execution specifications on immutable plan versions."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b16c8fd25439"
down_revision = "a05b7ec14328"
branch_labels = depends_on = None


def upgrade():
    op.add_column("conversation_plans", sa.Column("execution", postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column("conversation_plans", "execution")
