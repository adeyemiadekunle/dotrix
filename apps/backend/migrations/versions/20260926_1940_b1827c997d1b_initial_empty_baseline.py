"""initial empty baseline

Revision ID: b1827c997d1b
Revises:
Create Date: 2026-09-26 19:40:47.400667
"""

from collections.abc import Sequence

revision: str = "b1827c997d1b"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
