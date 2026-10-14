"""drop calendar feeds

Revision ID: 5d2f1c8e9a47
Revises: 73b64af5ac13
Create Date: 2026-10-12 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5d2f1c8e9a47"
down_revision: str | None = "73b64af5ac13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("calendar_feeds")


def downgrade() -> None:
    op.create_table(
        "calendar_feeds",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "scope",
            sa.Enum(
                "mine",
                "all",
                name="feedscope",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_calendar_feeds_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calendar_feeds")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_calendar_feeds_token_hash")),
        sa.UniqueConstraint("user_id", name=op.f("uq_calendar_feeds_user_id")),
    )
