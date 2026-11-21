"""coding_events.kind holds Kai's background task kinds ("background-running", "background-stopped")

Revision ID: c3a91f02d7e4
Revises: b5287c0a1a05
Create Date: 2026-11-20 13:40:00
"""

import sqlalchemy as sa
from alembic import op

revision = "c3a91f02d7e4"
down_revision = "b5287c0a1a05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("coding_events", "kind", type_=sa.String(32), existing_type=sa.String(16), existing_nullable=False)


def downgrade() -> None:
    op.execute("UPDATE coding_events SET kind = left(kind, 16)")
    op.alter_column("coding_events", "kind", type_=sa.String(16), existing_type=sa.String(32), existing_nullable=False)
