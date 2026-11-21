"""coding session profile digest: the SHA-256 of the system profile an fx session started with

Revision ID: e8d7b3241083
Revises: e47b209c6a18
Create Date: 2026-11-19 21:20:07.059474
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8d7b3241083"
down_revision: str | None = "e47b209c6a18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "coding_sessions", sa.Column("profile_digest", sa.String(length=64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("coding_sessions", "profile_digest")
