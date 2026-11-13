"""The versions of documents an agent run has read

Revision ID: 3d8a5f1c7b29
Revises: b83edb29b95d
Create Date: 2026-11-13 18:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3d8a5f1c7b29"
down_revision: str | None = "b83edb29b95d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("read_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_runs", "read_versions")
