"""conversations across projects

Revision ID: 0112d9f1cc4d
Revises: 19d1652c9593
Create Date: 2026-10-03 01:25:29.290559
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0112d9f1cc4d"
down_revision: str | None = "19d1652c9593"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs", sa.Column("project_ids", postgresql.ARRAY(sa.Uuid()), nullable=True)
    )
    op.alter_column("agent_runs", "project_id", existing_type=sa.UUID(), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM agent_runs WHERE project_id IS NULL")
    op.alter_column("agent_runs", "project_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("agent_runs", "project_ids")
