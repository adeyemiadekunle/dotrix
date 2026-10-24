"""Coding runs' worker leases (fencing tokens) and when recovery last checked them.

Revision ID: 8e3a6c2b4d19
Revises: 5d2f8c1a9e47
Create Date: 2026-10-24 12:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8e3a6c2b4d19"
down_revision: str | None = "5d2f8c1a9e47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("coding_runs", sa.Column("lease_token", sa.Integer(), server_default="0", nullable=False))
    op.add_column("coding_runs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("coding_runs", sa.Column("recovery_checked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("coding_runs", "recovery_checked_at")
    op.drop_column("coding_runs", "lease_expires_at")
    op.drop_column("coding_runs", "lease_token")
