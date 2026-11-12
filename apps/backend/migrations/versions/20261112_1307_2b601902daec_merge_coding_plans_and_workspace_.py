"""merge coding plans and workspace storage limit

Revision ID: 2b601902daec
Revises: c27d9ae36540, b12c45273954
Create Date: 2026-11-12 13:07:45.299813
"""

from collections.abc import Sequence

revision: str = "2b601902daec"
down_revision: str | Sequence[str] | None = ("c27d9ae36540", "b12c45273954")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
