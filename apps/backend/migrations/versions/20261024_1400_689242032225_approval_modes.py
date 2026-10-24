"""Approval modes: the workspace's cap, and the mode each agent run and coding turn was asked in.

Revision ID: 689242032225
Revises: b13bed5e43a9
Create Date: 2026-10-24 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "689242032225"
down_revision: str | None = "b13bed5e43a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("approval_mode", sa.String(length=16), nullable=True))
    op.add_column(
        "coding_runs",
        sa.Column("approval_mode", sa.String(length=16), server_default="manual", nullable=False),
    )
    op.add_column("workspaces", sa.Column("approval_mode_cap", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("workspaces", "approval_mode_cap")
    op.drop_column("coding_runs", "approval_mode")
    op.drop_column("agent_runs", "approval_mode")
