"""Personal default coding tool.

Revision ID: 92a31cd6ef04
Revises: 0080efad81e0
"""
import sqlalchemy as sa
from alembic import op

revision: str = "92a31cd6ef04"
down_revision: str | None = "0080efad81e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("default_coding_tool", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "default_coding_tool")
